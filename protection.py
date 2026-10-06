import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from telegram import Bot, Chat, User
from telegram.error import TelegramError
from telegram import ChatPermissions

from mtproto_client import mt
from database import db

LINK_RE = re.compile(
    r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/|telegram\.dog/|"
    r"tg://|(?:[a-z0-9-]+\.)+(?:com|net|org|io|me|co|in|ly|gg|cc|tv|xyz)(?:/|\b)|"
    r"@(?:[a-z][a-z0-9_]{3,31})\b)"
)

@dataclass
class ProtectionResult:
    detected: bool = False
    action: str = ""
    punished: bool = False
    warning_count: int = 0
    warning_limit: int = 3
    reason: str = ""
    bio: str = ""
    deleted: bool = False
    warning_message_id: int = 0
    warning_auto_delete: int = 0


def has_prohibited_link(text: str | None) -> bool:
    return bool(text and LINK_RE.search(text))


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False


async def check_and_ban(bot: Bot, chat_id: int, user: User, mt_entity=None, message_id: int | None = None, bio: str | None = None) -> ProtectionResult:
    """Fast bio protection using per-group settings.

    The function keeps the historical name for compatibility, but now supports
    ban/warning/mute modes and warning limits.
    """
    entity = mt_entity
    if entity is None:
        entity = await mt.refresh_entity(user.id)
    if entity is None:
        return ProtectionResult(reason="Bio lookup unavailable")

    if bio is None:
        bio = await mt.get_bio(entity)
    if bio is None or not has_prohibited_link(bio):
        return ProtectionResult(bio=bio or "")

    settings = await db.get_protection_settings(chat_id)
    mode = settings.get("message_action", "ban")
    raw_limit = int(settings.get("warning_limit", 3) or 0)
    limit = max(0, raw_limit)
    delete_after = bool(settings.get("delete_after_warning", True))
    warning_auto_delete = max(0, int(settings.get("warning_auto_delete", 0) or 0)) if mode == "warning" else 0

    result = ProtectionResult(detected=True, action=mode, warning_limit=limit, bio=bio,
                              reason="Prohibited link detected in bio", warning_auto_delete=warning_auto_delete)

    # Direct punishment mode: no warning message is sent.
    if mode == "ban":
        try:
            await bot.ban_chat_member(chat_id, user.id)
            await db.record_user_banned(user.id, chat_id)
            if message_id:
                try:
                    await bot.delete_message(chat_id, message_id)
                    result.deleted = True
                except TelegramError:
                    pass
            result.punished = True
            result.action = "ban"
            return result
        except TelegramError as exc:
            result.reason = f"Ban failed: {exc}"
            return result

    # Warning mode: do the warning counter update and message deletion in
    # parallel. Both are independent network operations, so waiting for one
    # before starting the other unnecessarily delays the warning.
    count_task = asyncio.create_task(db.increment_warning(chat_id, user.id))
    delete_task = None
    if delete_after and message_id:
        delete_task = asyncio.create_task(bot.delete_message(chat_id, message_id))

    count = await count_task
    result.warning_count = count

    if delete_task is not None:
        try:
            await delete_task
            result.deleted = True
        except TelegramError:
            pass

    # Apply configured punishment once the limit is reached.
    if limit > 0 and count >= limit:
        punishment = settings.get("punishment", "mute")
        try:
            if punishment == "ban":
                await bot.ban_chat_member(chat_id, user.id)
                await db.record_user_banned(user.id, chat_id)
                result.punished = True
                result.action = "ban"
            else:
                await bot.restrict_chat_member(
                    chat_id,
                    user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
                result.punished = True
                result.action = "mute"
        except TelegramError as exc:
            result.reason = f"{punishment.title()} failed: {exc}"

    return result


async def send_group_warning(bot: Bot, chat: Chat, user: User, result: ProtectionResult):
    if not result.detected or result.action not in ("warning", "mute"):
        return
    try:
        if result.punished:
            action_text = "🔨 User banned" if result.action == "ban" else "🔇 User muted"
            text = (
                "🚨 <b>Bio Link Protector</b>\n\n"
                f"👤 {user.mention_html()}\n"
                f"⚠️ Warning {result.warning_count}/{result.warning_limit}\n"
                f"{action_text}\n"
                "🔗 Prohibited link detected in bio."
            )
        else:
            text = (
                "⚠️ <b>Bio Link Warning</b>\n\n"
                f"👤 {user.mention_html()}\n"
                f"⚠️ Warning {result.warning_count}/{result.warning_limit}\n"
                "🔗 Prohibited link detected in bio."
            )
        sent = await bot.send_message(chat.id, text, parse_mode="HTML", disable_web_page_preview=True)
        # Auto-delete only the warning notification. The offending user message
        # is controlled separately by the "Delete after Warning" setting.
        if result.warning_auto_delete > 0:
            async def _delete_warning_later():
                await asyncio.sleep(min(result.warning_auto_delete, 86400))
                try:
                    await bot.delete_message(chat.id, sent.message_id)
                except TelegramError:
                    pass
            asyncio.create_task(_delete_warning_later())
    except TelegramError:
        pass


# Kept for compatibility with older imports. Direct-ban warnings are intentionally
# not sent by the new protection flow.
async def send_admin_warning(bot: Bot, chat: Chat, user: User, reason: str, bio: str = ""):
    return
