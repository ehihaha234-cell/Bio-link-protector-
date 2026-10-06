import asyncio
import logging
import threading

from health_server import run_health_server
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ChatMemberHandler,
    ContextTypes, filters, CallbackQueryHandler
)
from telegram import Bot
from telethon import events

from config import BOT_TOKEN, OWNER_ID
from database import db
from protection import check_and_ban, is_admin, send_admin_warning
from auto_delete import schedule_delete
from owner import owner_start, owner_broadcast, owner_stats, owner_groups, mtproto_menu, mtlogin, mtlogout, mtlogin_message, owner_callback, owner_broadcast_message, user_start, user_settings_callback
from mtproto_client import mt
from setup_flow import setup_mtproto_for_group

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def mt_message_handler(event):
    if not event.is_group:
        return
    try:
        chat_id = int(event.chat_id)
        if await db.is_group_paused(chat_id):
            return
        sender = await event.get_sender()
        if not sender or getattr(sender, "bot", False):
            return
        async with Bot(BOT_TOKEN) as bot:
            from telegram import User
            # Run the Bot API admin check and MTProto bio lookup in parallel.
            member_task = asyncio.create_task(bot.get_chat_member(chat_id, sender.id))
            bio_task = asyncio.create_task(mt.get_bio(sender))
            member, bio = await asyncio.gather(member_task, bio_task)
            if member.status in ("administrator", "creator"):
                return
            u = User(id=sender.id, first_name=getattr(sender, "first_name", None) or "User",
                     last_name=getattr(sender, "last_name", None), username=getattr(sender, "username", None), is_bot=False)
            result = await check_and_ban(bot, chat_id, u, sender, message_id=event.id, bio=bio)
            if result.detected and result.action in ("warning", "mute"):
                from protection import send_group_warning
                await send_group_warning(bot, await bot.get_chat(chat_id), u, result)
    except Exception:
        logger.exception("MTProto message protection failed")


async def mt_chat_action_handler(event):
    if not event.is_group or not (event.user_joined or event.user_added):
        return
    try:
        chat_id = int(event.chat_id)
        if await db.is_group_paused(chat_id):
            return
        settings = await db.get_protection_settings(chat_id)
        if not settings.get("detect_on_join", True):
            return
        sender = await event.get_user()
        if not sender or getattr(sender, "bot", False):
            return
        async with Bot(BOT_TOKEN) as bot:
            from telegram import User
            member_task = asyncio.create_task(bot.get_chat_member(chat_id, sender.id))
            bio_task = asyncio.create_task(mt.get_bio(sender))
            member, bio = await asyncio.gather(member_task, bio_task)
            if member.status in ("administrator", "creator"):
                return
            u = User(id=sender.id, first_name=getattr(sender, "first_name", None) or "User",
                     last_name=getattr(sender, "last_name", None), username=getattr(sender, "username", None), is_bot=False)
            result = await check_and_ban(bot, chat_id, u, sender, bio=bio)
            if result.detected and result.action in ("warning", "mute"):
                from protection import send_group_warning
                await send_group_warning(bot, await bot.get_chat(chat_id), u, result)
    except Exception:
        logger.exception("MTProto join protection failed")

def _run_mtproto():
    async def runner():
        mt.set_handlers(mt_message_handler,mt_chat_action_handler)
        while True:
            try:
                await mt.start(); break
            except Exception as e:
                logger.info("MTProto waiting for Owner login: %s",e)
                await asyncio.sleep(10)
        await mt.client.run_until_disconnected()
    asyncio.run(runner())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id == OWNER_ID:
        logger.info("Owner /start received from Telegram user id=%s", user.id)
        await owner_start(update, context)
        return
    await db.record_user_start(user.id)
    await user_start(update, context)


async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP) or not user:
        return

    await db.ensure_group(chat.id, chat.title or str(chat.id), chat.type)
    if await db.is_group_paused(chat.id):
        return

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

    # One owner MTProto user account is shared by all protected groups.
    # It joins each group automatically during setup.
    threading.Thread(target=_run_mtproto, daemon=True, name="mtproto").start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(owner_callback, pattern=r"^owner:"))
    app.add_handler(CallbackQueryHandler(user_settings_callback, pattern=r"^groupcfg:"))
    app.add_handler(CommandHandler("broadcast", owner_broadcast))
    app.add_handler(CommandHandler("stats", owner_stats))
    app.add_handler(CommandHandler("groups", owner_groups))
    app.add_handler(CommandHandler("mtproto", mtproto_menu))
    app.add_handler(CommandHandler("mtlogin", mtlogin))
    app.add_handler(CommandHandler("mtlogout", mtlogout))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, owner_broadcast_message), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mtlogin_message), group=1)
    app.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, group_message))

    logger.info("Bio Link Protector started with Bot API + MTProto")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
