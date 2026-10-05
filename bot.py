import asyncio
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    BOT_TOKEN,
    CHECK_BIO_ON_JOIN,
    CHECK_BIO_ON_MESSAGE,
    OWNER_ID,
)
from database import (
    count_groups,
    get_due_messages,
    get_group,
    get_stat,
    init_db,
    list_active_groups,
    mark_group_inactive,
    queue_message,
    remove_queued_message,
    set_auto_delete,
    upsert_group,
)
from protection import ban_and_warn, fetch_bio, has_prohibited_link


async def ensure_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return None
    await upsert_group(chat.id, chat.title or "Untitled Group")
    return await get_group(chat.id)


async def process_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user, source_message=None):
    if not user or user.is_bot:
        return False
    bio = await fetch_bio(context, user.id)
    if not has_prohibited_link(bio):
        return False
    if source_message:
        return await ban_and_warn(context, source_message, bio)
    # For join events there is no message to delete; create a synthetic-safe action through bot API.
    chat = update.effective_chat
    try:
        await context.bot.ban_chat_member(chat.id, user.id)
    except TelegramError:
        return False
    # Send a warning using a temporary message so ban_and_warn's notification logic isn't duplicated.
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        creator = next((a for a in admins if a.status == ChatMemberStatus.OWNER), None)
        if creator:
            await context.bot.send_message(
                creator.user.id,
                "🚨 <b>Bio Link Protector Warning</b>\n\n"
                f"👤 User: {user.full_name}\n"
                f"🆔 User ID: <code>{user.id}</code>\n"
                f"👥 Group: <b>{chat.title or 'Unknown'}</b>\n\n"
                "🛡️ Action: <b>Banned</b>\n"
                "🔗 Reason: Link detected in bio",
                parse_mode="HTML",
            )
    except TelegramError:
        pass
    return True


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    group = await ensure_group(update, context)

    # Protection is checked before auto-delete queueing.
    if CHECK_BIO_ON_MESSAGE and message.from_user:
        banned = await process_user(update, context, message.from_user, message)
        if banned:
            return

    seconds = int((group or {}).get("auto_delete_seconds", 0))
    if seconds > 0:
        await queue_message(
            chat.id,
            message.message_id,
            datetime.now(timezone.utc) + timedelta(seconds=seconds),
        )


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm:
        return
    chat = cm.chat
    await upsert_group(chat.id, chat.title or "Untitled Group")

    new_status = cm.new_chat_member.status
    old_status = cm.old_chat_member.status
    joined = new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED) and old_status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.BANNED,
    )
    if joined and CHECK_BIO_ON_JOIN:
        await process_user(update, context, cm.new_chat_member.user)

    # If our bot leaves/is removed, mark the group inactive.
    if cm.new_chat_member.user.id == context.bot.id and new_status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.BANNED,
    ):
        await mark_group_inactive(chat.id)


async def cleanup_loop(application: Application):
    while True:
        try:
            due = await get_due_messages()
            for doc in due:
                try:
                    await application.bot.delete_message(doc["chat_id"], doc["message_id"])
                except TelegramError:
                    pass
                finally:
                    await remove_queued_message(doc["_id"])
        except Exception:
            pass
        await asyncio.sleep(5)


async def post_init(application: Application):
    await init_db()
    application.create_task(cleanup_loop(application))
    try:
        await application.bot.set_my_default_administrator_rights(
            rights={"can_delete_messages": True, "can_restrict_members": True},
            for_channels=False,
        )
    except Exception:
        pass


# ---------- Owner dashboard ----------

def owner_only(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == OWNER_ID)


async def owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast")],
        [InlineKeyboardButton("📊 Statistics", callback_data="owner_stats"), InlineKeyboardButton("👥 Groups", callback_data="owner_groups")],
        [InlineKeyboardButton("🗑️ Auto Delete Settings", callback_data="owner_autodelete")],
    ])
    await update.message.reply_text("🤖 <b>Bio Link Protector Owner Panel</b>", parse_mode="HTML", reply_markup=keyboard)


async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or q.from_user.id != OWNER_ID:
        return
    await q.answer()
    if q.data == "owner_stats":
        total = await count_groups(False)
        active = await count_groups(True)
        banned = await get_stat("banned_users")
        await q.edit_message_text(
            f"📊 <b>Statistics</b>\n\n👥 Total Groups: <b>{total}</b>\n🟢 Active Groups: <b>{active}</b>\n🚫 Banned Users: <b>{banned}</b>",
            parse_mode="HTML",
        )
    elif q.data == "owner_groups":
        gs = await list_active_groups()
        if not gs:
            text = "👥 <b>Groups</b>\n\nNo active groups found."
        else:
            lines = ["👥 <b>Active Groups</b>", ""]
            for i, g in enumerate(gs[:100], 1):
                lines.append(f"{i}. {g.get('title', 'Untitled')} — <code>{g['chat_id']}</code>")
            text = "\n".join(lines)
        await q.edit_message_text(text, parse_mode="HTML")
    elif q.data == "owner_autodelete":
        await q.edit_message_text(
            "🗑️ <b>Auto Delete</b>\n\n"
            "Set it inside a group with:\n"
            "<code>/autodelete 60</code>\n\n"
            "Use <code>0</code> to disable.",
            parse_mode="HTML",
        )
    elif q.data == "owner_broadcast":
        context.user_data["awaiting_broadcast"] = True
        await q.edit_message_text("📢 Send the message you want to broadcast to all active groups.")


async def owner_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update) or not context.user_data.get("awaiting_broadcast"):
        return
    context.user_data["awaiting_broadcast"] = False
    groups = await list_active_groups()
    sent = 0
    failed = 0
    for g in groups:
        try:
            await update.effective_message.copy(chat_id=g["chat_id"])
            sent += 1
        except TelegramError:
            failed += 1
            await mark_group_inactive(g["chat_id"])
        await asyncio.sleep(0.05)
    await update.effective_message.reply_text(f"📢 Broadcast finished.\n\n✅ Sent: {sent}\n❌ Failed: {failed}")


async def autodelete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if not context.args or not context.args[0].isdigit():
        if user and await is_group_admin(update, context):
            await update.message.reply_text("Usage: /autodelete <seconds>\nExample: /autodelete 60\nUse 0 to disable.")
        return
    if not await is_group_admin(update, context):
        return
    seconds = int(context.args[0])
    if seconds < 0 or seconds > 7 * 24 * 3600:
        await update.message.reply_text("Use a value from 0 to 604800 seconds.")
        return
    await upsert_group(chat.id, chat.title or "Untitled Group")
    await set_auto_delete(chat.id, seconds)
    await update.message.reply_text("🗑️ Auto Delete disabled." if seconds == 0 else f"🗑️ Auto Delete set to {seconds} seconds.")


async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except TelegramError:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if owner_only(update):
        await owner_start(update, context)
        return
    await update.message.reply_text("🛡️ Bio Link Protector is active. Add me as an administrator to protect your group.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    # Keep production polling alive; detailed exception logging can be added later.
    print(f"Telegram error: {context.error!r}")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("autodelete", autodelete_command))
    app.add_handler(CallbackQueryHandler(owner_callback, pattern=r"^owner_"))
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, on_message), group=10)
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE, owner_broadcast_message), group=20)
    app.add_error_handler(error_handler)

    print("Bio Link Protector started")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
