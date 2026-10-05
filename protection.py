import re
from dataclasses import dataclass

from telegram import Bot, Chat, User
from telegram.error import TelegramError

LINK_RE = re.compile(
    r"(?i)(https?://|www\.|t\.me/|telegram\.me/|telegram\.dog/|"
    r"@[a-z][a-z0-9_]{3,31}\b)"
)

@dataclass
class ProtectionResult:
    banned: bool
    reason: str = ""

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False

async def fetch_bio(bot: Bot, user: User):
    """
    Bot API limitation: a bot cannot arbitrarily fetch every group member's
    bio by user ID. Telegram exposes bio in supported contexts such as
    private-chat Chat data and join-request updates.

    This function therefore returns a bio only when it is actually available
    on the supplied User object/context. It never invents profile data.
    """
    return getattr(user, "bio", None)

def has_prohibited_link(text: str | None) -> bool:
    if not text:
        return False
    return bool(LINK_RE.search(text))

async def process_user(bot: Bot, chat_id: int, user: User) -> ProtectionResult:
    bio = await fetch_bio(bot, user)
    if not has_prohibited_link(bio):
        return ProtectionResult(False)

    try:
        await bot.ban_chat_member(chat_id, user.id)
        return ProtectionResult(True, "Prohibited link detected in bio")
    except TelegramError as exc:
        return ProtectionResult(False, f"Ban failed: {exc}")

async def send_admin_warning(bot: Bot, chat: Chat, user: User, reason: str):
    text = (
        "🚨 Bio Link Protector Warning\n\n"
        f"👤 User: {user.mention_html()}\n"
        f"🆔 User ID: <code>{user.id}</code>\n\n"
        f"🛡️ Action: User Banned\n"
        f"🔗 Reason: {reason}\n\n"
        "Your group is protected by Bio Link Protector."
    )
    try:
        admins = await bot.get_chat_administrators(chat.id)
        for admin in admins:
            if admin.user.is_bot:
                continue
            try:
                await bot.send_message(
                    admin.user.id, text, parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except TelegramError:
                # Admin may have never started the bot; Telegram will reject DM.
                pass
    except TelegramError:
        pass
