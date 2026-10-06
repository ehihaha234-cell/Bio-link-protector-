import re
from dataclasses import dataclass

from telegram import Bot, Chat, User
from telegram.error import TelegramError

from mtproto_client import mt

# Detect normal URLs, Telegram links/usernames and common bare domains.
LINK_RE = re.compile(
    r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/|telegram\.dog/|"
    r"tg://|(?:[a-z0-9-]+\.)+(?:com|net|org|io|me|co|in|ly|gg|cc|tv|xyz)(?:/|\b)|"
    r"@(?:[a-z][a-z0-9_]{3,31})\b)"
)

@dataclass
class ProtectionResult:
    banned: bool
    reason: str = ""
    bio: str = ""

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False

def has_prohibited_link(text: str | None) -> bool:
    if not text:
        return False
    return bool(LINK_RE.search(text))

async def check_and_ban(bot: Bot, chat_id: int, user: User, mt_entity=None) -> ProtectionResult:
    """Read the current Telegram profile bio with the MTProto user account."""
    entity = mt_entity
    if entity is None:
        entity = await mt.refresh_entity(user.id)
    if entity is None:
        return ProtectionResult(False, "Bio lookup unavailable")

    bio = await mt.get_bio(entity)
    if bio is None:
        return ProtectionResult(False, "Bio lookup unavailable")

    if not has_prohibited_link(bio):
        return ProtectionResult(False, bio=bio)

    try:
        await bot.ban_chat_member(chat_id, user.id)
        try:
            from database import db
            await db.record_user_banned(user.id, chat_id)
        except Exception:
            pass
        return ProtectionResult(True, "Prohibited link detected in bio", bio=bio)
    except TelegramError as exc:
        return ProtectionResult(False, f"Ban failed: {exc}", bio=bio)

async def send_admin_warning(bot: Bot, chat: Chat, user: User, reason: str, bio: str = ""):
    text = (
        "🚨 Bio Link Protector Warning\n\n"
        f"👤 User: {user.mention_html()}\n"
        f"🆔 User ID: <code>{user.id}</code>\n\n"
        "🛡️ Action: User Banned\n"
        f"🔗 Reason: {reason}\n"
    )
    if bio:
        safe_bio = bio.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text += f"\n📝 Bio: <code>{safe_bio}</code>\n"
    text += "\nYour group is protected by Bio Link Protector."

    try:
        admins = await bot.get_chat_administrators(chat.id)
        # The Owner MTProto detector account is an administrator in protected
        # groups. Do not send protection-warning DMs to that detector account.
        detector_id = None
        try:
            detector = await mt.get_me()
            detector_id = int(detector.id) if detector else None
        except Exception:
            detector_id = None

        for admin in admins:
            if admin.user.is_bot or (detector_id and admin.user.id == detector_id):
                continue
            try:
                await bot.send_message(
                    admin.user.id, text, parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except TelegramError:
                pass
    except TelegramError:
        pass
