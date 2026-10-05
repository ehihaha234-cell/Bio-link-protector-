import asyncio
import logging
import threading

from health_server import run_health_server
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ChatMemberHandler,
    ContextTypes, filters
)
from telegram import Bot
from telethon import events

from config import BOT_TOKEN, OWNER_ID
from database import db
from protection import check_and_ban, is_admin, send_admin_warning
from auto_delete import schedule_delete
from owner import owner_start, owner_broadcast, owner_stats, owner_groups
from mtproto_client import mt
from setup_flow import setup_mtproto_for_group

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _run_mtproto():
    async def runner():
        client = await mt.start()

        @client.on(events.NewMessage())
        async def on_new_message(event):
            if not event.is_group:
                return
            try:
                sender = await event.get_sender()
                if not sender or getattr(sender, "bot", False):
                    return
                if not getattr(sender, "id", None):
                    return
                logger.info("Bio check: message from user %s in chat %s", sender.id, event.chat_id)
                # Full user gives us the current bio/about field.
                async with Bot(BOT_TOKEN) as bot:
                    chat_id = int(event.chat_id)
                    user = await bot.get_chat_member(chat_id, sender.id)
                    if user.status in ("administrator", "creator"):
                        return
                    tg_user = sender
                    # Build a lightweight Bot API-compatible user object.
                    from telegram import User
                    api_user = User(
                        id=sender.id,
                        first_name=getattr(sender, "first_name", None) or "User",
                        last_name=getattr(sender, "last_name", None),
                        username=getattr(sender, "username", None),
                        is_bot=bool(getattr(sender, "bot", False)),
                    )
                    result = await check_and_ban(bot, chat_id, api_user, sender)
                    logger.info(
                        "Bio check result: user=%s chat=%s banned=%s reason=%s bio=%r",
                        sender.id, chat_id, result.banned, result.reason, result.bio,
                    )
                    if result.banned:
                        try:
                            await bot.delete_message(chat_id, event.id)
                        except Exception:
                            pass
                        try:
                            chat = await bot.get_chat(chat_id)
                            await send_admin_warning(bot, chat, api_user, result.reason, result.bio)
                        except Exception:
                            pass
            except Exception:
                logger.exception("MTProto message protection failed")

        @client.on(events.ChatAction())
        async def on_chat_action(event):
            if not event.is_group or not (event.user_joined or event.user_added):
                return
            try:
                sender = await event.get_user()
                if not sender or getattr(sender, "bot", False):
                    return
                async with Bot(BOT_TOKEN) as bot:
                    chat_id = int(event.chat_id)
                    member = await bot.get_chat_member(chat_id, sender.id)
                    if member.status in ("administrator", "creator"):
                        return
                    from telegram import User
                    api_user = User(
                        id=sender.id,
                        first_name=getattr(sender, "first_name", None) or "User",
                        last_name=getattr(sender, "last_name", None),
                        username=getattr(sender, "username", None),
                        is_bot=bool(getattr(sender, "bot", False)),
                    )
                    result = await check_and_ban(bot, chat_id, api_user, sender)
                    if result.banned:
                        chat = await bot.get_chat(chat_id)
                        await send_admin_warning(bot, chat, api_user, result.reason, result.bio)
            except Exception:
                logger.exception("MTProto join protection failed")

        logger.info("MTProto bio protection listener started; monitoring group messages and joins")
        await client.run_until_disconnected()

    asyncio.run(runner())


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

    # MTProto listener performs the actual bio lookup/ban. This handler only
    # handles message retention and database bookkeeping.
    await schedule_delete(context, msg)


async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or not update.effective_chat:
        return
    chat = update.effective_chat
    await db.ensure_group(chat.id, chat.title or str(chat.id), chat.type)


async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.my_chat_member
    if not cm or not update.effective_chat:
        return
    chat = update.effective_chat
    new_status = cm.new_chat_member.status
    if new_status == "administrator":
        await db.ensure_group(chat.id, chat.title or str(chat.id), chat.type)
        # When the bot becomes an administrator, automatically verify the
        # required rights, invite the MTProto account, and promote it.
        await setup_mtproto_for_group(
            context.bot, chat.id, chat.title or str(chat.id), cm.from_user
        )
    elif new_status == "member":
        await db.ensure_group(chat.id, chat.title or str(chat.id), chat.type)
    elif new_status in ("left", "kicked"):
        await db.deactivate_group(chat.id)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    Thread = threading.Thread
    Thread(target=run_health_server, daemon=True).start()

    # MTProto account is a separate Telegram user account. It must already be
    # logged in via MT_SESSION and must be a member of protected groups.
    threading.Thread(target=_run_mtproto, daemon=True, name="mtproto").start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", owner_broadcast))
    app.add_handler(CommandHandler("stats", owner_stats))
    app.add_handler(CommandHandler("groups", owner_groups))
    app.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, group_message))

    logger.info("Bio Link Protector started with Bot API + MTProto")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
