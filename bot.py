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
from owner import owner_start, owner_broadcast, owner_stats, owner_groups, mtproto_menu, mtlogin, mtlogout, mtlogin_message, owner_callback, owner_broadcast_message
from mtproto_client import mt
from setup_flow import setup_mtproto_for_group

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def mt_message_handler(event):
    if not event.is_group:return
    try:
        if await db.is_group_paused(int(event.chat_id)):
            return
        sender=await event.get_sender()
        if not sender or getattr(sender,"bot",False):return
        async with Bot(BOT_TOKEN) as bot:
            from telegram import User
            member=await bot.get_chat_member(int(event.chat_id),sender.id)
            if member.status in ("administrator","creator"):return
            u=User(id=sender.id,first_name=getattr(sender,"first_name",None) or "User",last_name=getattr(sender,"last_name",None),username=getattr(sender,"username",None),is_bot=False)
            result=await check_and_ban(bot,int(event.chat_id),u,sender)
            if result.banned:
                try:await bot.delete_message(int(event.chat_id),event.id)
                except:pass
                try:await send_admin_warning(bot,await bot.get_chat(int(event.chat_id)),u,result.reason,result.bio)
                except:pass
    except Exception:logger.exception("MTProto message protection failed")

async def mt_chat_action_handler(event):
    if not event.is_group or not (event.user_joined or event.user_added):return
    try:
        if await db.is_group_paused(int(event.chat_id)):
            return
        sender=await event.get_user()
        if not sender or getattr(sender,"bot",False):return
        async with Bot(BOT_TOKEN) as bot:
            from telegram import User
            member=await bot.get_chat_member(int(event.chat_id),sender.id)
            if member.status in ("administrator","creator"):return
            u=User(id=sender.id,first_name=getattr(sender,"first_name",None) or "User",last_name=getattr(sender,"last_name",None),username=getattr(sender,"username",None),is_bot=False)
            result=await check_and_ban(bot,int(event.chat_id),u,sender)
            if result.banned: await send_admin_warning(bot,await bot.get_chat(int(event.chat_id)),u,result.reason,result.bio)
    except Exception:logger.exception("MTProto join protection failed")

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
    await update.message.reply_text(
        "🛡️ Bio Link Protector is active.\n\n"
        "Add me as an administrator with <b>all administrator permissions</b>.\n\n"
        "Required permissions include:\n"
        "• Manage chat\n"
        "• Change group info\n"
        "• Delete messages\n"
        "• Invite users / create invite links\n"
        "• Ban/restrict users\n"
        "• Pin messages\n"
        "• Manage video chats\n"
        "• Add new admins\n"
        "• Manage topics\n\n"
        "If any permission is missing, I will tell the admin exactly which permission must be enabled.",
        parse_mode="HTML",
    )


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
