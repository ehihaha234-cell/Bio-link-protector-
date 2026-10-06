import re
from dataclasses import dataclass

from telegram import Bot, Chat, User
from telegram.error import TelegramError

from mtproto_client import mt
from database import db

LINK_RE = re.compile(
    r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/|telegram\.dog/|"
    r"tg://|(?:[a-z0-9-]+\.)+(?:com|net|org|io|me|co|in|ly|gg|cc|tv|xyz)(?:/|\b)|"
    r"@(?:[a-z][a-z0-9_]{3,31})\b)"
)

@dataclass
class ProtectionResult:
    detected: bool
    action: str = ""
    reason: str = ""
    bio: str = ""

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False

def has_prohibited_link(text: str | None) -> bool:
    return bool(text and LINK_RE.search(text))

async def apply_punishment(bot: Bot, chat_id: int, user_id: int, punishment: str) -> bool:
    try:
        if punishment == "mute":
            from telegram import ChatPermissions
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
            )
        else:
            await bot.ban_chat_member(chat_id, user_id)
        if punishment == "ban":
            await db.record_user_banned(user_id, chat_id)
        return True
    except TelegramError:
        return False

async def check_and_ban(bot: Bot, chat_id: int, user: User, mt_entity=None, trigger="message") -> ProtectionResult:
    entity = mt_entity or await mt.refresh_entity(user.id)
    if entity is None:
        return ProtectionResult(False, reason="Bio lookup unavailable")

    bio = await mt.get_bio(entity)
    if bio is None or not has_prohibited_link(bio):
        return ProtectionResult(False, bio=bio or "")

    settings = await db.get_group_settings(chat_id)

    if trigger == "join" and not settings.get("detect_on_join", True):
        return ProtectionResult(True, action="ignored", reason="Join detection disabled", bio=bio)

    if trigger == "message" and settings.get("message_action", "punish") == "warn":
        return ProtectionResult(True, action="warn", reason="Prohibited link detected in bio", bio=bio)

    punishment = settings.get("punishment", "ban")
    ok = await apply_punishment(bot, chat_id, user.id, punishment)
    action = "User Muted" if punishment == "mute" else "User Banned"
    if ok:
        return ProtectionResult(True, action=action, reason="Prohibited link detected in bio", bio=bio)
    return ProtectionResult(True, action="punishment_failed", reason="Punishment failed", bio=bio)

async def send_user_warning(bot: Bot, chat_id: int, user: User, bio: str = ""):
    try:
        return await bot.send_message(
            chat_id,
            f"⚠️ <b>Bio Link Warning</b>\n\n👤 {user.mention_html()}\n\n"
            "Your profile bio contains a prohibited link. Please remove it to avoid further action.",
            parse_mode="HTML",
        )
    except TelegramError:
        return None

async def send_admin_warning(bot: Bot, chat: Chat, user: User, reason: str, bio: str = "", action: str = "User Banned"):
    text = (
        "🚨 <b>Bio Link Protector Warning</b>\n\n"
        f"👤 User: {user.mention_html()}\n"
        f"🆔 User ID: <code>{user.id}</code>\n\n"
        f"🛡️ Action: {action}\n"
        f"🔗 Reason: {reason}\n"
    )
    if bio:
        safe_bio = bio.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text += f"\n📝 Bio: <code>{safe_bio}</code>\n"
    text += "\nYour group is protected by Bio Link Protector."
    try:
        admins = await bot.get_chat_administrators(chat.id)
        detector_id = None
        try:
            detector = await mt.get_me()
            detector_id = int(detector.id) if detector else None
        except Exception:
            pass
        for admin in admins:
            if admin.user.is_bot or (detector_id and admin.user.id == detector_id):
                continue
            try:
                await bot.send_message(admin.user.id, text, parse_mode="HTML", disable_web_page_preview=True)
            except TelegramError:
                pass
    except TelegramError:
        pass
