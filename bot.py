import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ChatMemberHandler,
    ContextTypes, filters
)

from config import BOT_TOKEN, OWNER_ID
from database import db
from protection import process_user, is_admin, send_admin_warning
from auto_delete import schedule_delete
from owner import owner_start, owner_broadcast, owner_stats, owner_groups

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and update.effective_user.id == OWNER_ID:
        await owner_start(update, context)
        return
    await update.message.reply_text(
        "🛡️ Bio Link Protector is active.\n\n"
        "Add me as an administrator to a group with permission to ban users "
        "and delete messages. Protection works automatically."
    )


async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP) or not user:
        return

    await db.ensure_group(chat.id, chat.title or str(chat.id), chat.type)

    # Never punish group administrators.
    if await is_admin(context.bot, chat.id, user.id):
        return

    result = await process_user(context.bot, chat.id, user)
    if result.banned:
        try:
            await msg.delete()
        except Exception:
            pass
        await send_admin_warning(context.bot, chat, user, result.reason)
        return

    await schedule_delete(context, msg)


async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or not update.effective_chat:
        return

    chat = update.effective_chat
    await db.ensure_group(chat.id, chat.title or str(chat.id), chat.type)

    new = cm.new_chat_member
    old = cm.old_chat_member

    # A user becoming a member from left/kicked/restricted state.
    became_member = (
        new.status in ("member", "restricted")
        and old.status in ("left", "kicked")
    )
    if not became_member:
        return

    user = new.user
    if await is_admin(context.bot, chat.id, user.id):
        return

    result = await process_user(context.bot, chat.id, user)
    if result.banned:
        await send_admin_warning(context.bot, chat, user, result.reason)


async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.my_chat_member
    if not cm or not update.effective_chat:
        return
    chat = update.effective_chat
    new_status = cm.new_chat_member.status
    if new_status in ("administrator", "member"):
        await db.ensure_group(chat.id, chat.title or str(chat.id), chat.type)
    elif new_status in ("left", "kicked"):
        await db.deactivate_group(chat.id)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", owner_broadcast))
    app.add_handler(CommandHandler("stats", owner_stats))
    app.add_handler(CommandHandler("groups", owner_groups))

    app.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, group_message))

    logger.info("Bio Link Protector started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
