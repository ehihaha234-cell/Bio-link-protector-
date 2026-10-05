import logging
import re
from telegram import Bot
from telegram.error import TelegramError
from telegram.constants import ChatMemberStatus
from telethon.errors import UserAlreadyParticipantError
from mtproto_client import mt

logger = logging.getLogger(__name__)

REQUIRED = {
    "can_restrict_members": "Ban/restrict users",
    "can_delete_messages": "Delete messages",
    "can_invite_users": "Invite users / create invite links",
    "can_promote_members": "Add new admins",
}

async def check_bot_admin_rights(bot: Bot, chat_id: int):
    me = await bot.get_me()
    member = await bot.get_chat_member(chat_id, me.id)
    if member.status != ChatMemberStatus.ADMINISTRATOR:
        return False, ["Administrator"]

    missing = []
    for attr, label in REQUIRED.items():
        if not bool(getattr(member, attr, False)):
            missing.append(label)
    return not missing, missing

async def _notify(bot: Bot, chat_id: int, actor, text: str):
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        pass
    if actor and getattr(actor, "id", None):
        try:
            await bot.send_message(actor.id, text)
        except Exception:
            pass

async def setup_mtproto_for_group(bot: Bot, chat_id: int, title: str, actor=None):
    """Automatically connect the MTProto account to a group and promote it."""
    try:
        ok, missing = await check_bot_admin_rights(bot, chat_id)
    except TelegramError as exc:
        logger.warning("Cannot inspect bot admin rights in %s: %s", chat_id, exc)
        return False

    if not ok:
        missing_text = "\n".join(f"• {x}" for x in missing)
        await _notify(
            bot, chat_id, actor,
            "⚠️ <b>Admin Permissions Required</b>\n\n"
            "I need the following admin permissions before Link Protector can be enabled:\n"
            f"{missing_text}\n\n"
            "Please give me these permissions, then add/restart the bot setup.",
        )
        return False

    try:
        invite = await bot.create_chat_invite_link(
            chat_id=chat_id,
            name="Bio Link Protector MTProto setup",
        )
        invite_link = invite.invite_link
        logger.info("Created MTProto setup invite for %s: %s", chat_id, invite_link)

        # The MTProto user account uses the invite link to join the group.
        await mt.join_group_by_invite(invite_link)

        me = await mt.client.get_me()
        mt_user_id = int(me.id)

        # Give the MTProto account administrator rights after it joins.
        try:
            await bot.promote_chat_member(
                chat_id=chat_id,
                user_id=mt_user_id,
                can_manage_chat=True,
                can_change_info=True,
                can_delete_messages=True,
                can_invite_users=True,
                can_restrict_members=True,
                can_pin_messages=True,
                can_manage_video_chats=True,
                can_promote_members=True,
                can_manage_topics=True,
            )
        except TelegramError as first_exc:
            # Some groups/Telegram configurations do not allow an admin to
            # delegate the promote-admin right. Retry with the other rights.
            logger.warning("Full MTProto promotion failed in %s: %s; retrying without can_promote_members", chat_id, first_exc)
            await bot.promote_chat_member(
                chat_id=chat_id,
                user_id=mt_user_id,
                can_manage_chat=True,
                can_change_info=True,
                can_delete_messages=True,
                can_invite_users=True,
                can_restrict_members=True,
                can_pin_messages=True,
                can_manage_video_chats=True,
                can_promote_members=False,
                can_manage_topics=True,
            )

        logger.info("MTProto account %s joined and was promoted in %s", mt_user_id, chat_id)
        await _notify(
            bot, chat_id, actor,
            "✅ <b>Bio Link Protector setup completed</b>\n\n"
            "🤖 Bot permissions verified.\n"
            "👤 MTProto account joined the group.\n"
            "🛡️ MTProto account was promoted to administrator.\n\n"
            "Bio-link protection is now ready.",
        )
        return True
    except Exception as exc:
        logger.exception("Automatic MTProto group setup failed for %s", chat_id)
        await _notify(
            bot, chat_id, actor,
            "❌ <b>MTProto setup failed</b>\n\n"
            f"<code>{str(exc)[:500]}</code>\n\n"
            "Please make sure the MTProto account/session is valid and try again.",
        )
        return False
