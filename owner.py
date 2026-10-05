from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_ID
from database import db

def owner_only(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id == OWNER_ID)

async def owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        return
    groups = await db.count_groups()
    await update.effective_message.reply_text(
        "👑 Bio Link Protector Owner Panel\n\n"
        f"👥 Active Groups: {groups}\n\n"
        "Commands:\n"
        "/broadcast - Broadcast a text message to all active groups\n"
        "/stats - View statistics\n"
        "/groups - View groups"
    )

async def owner_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        return
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text(
            "Usage:\n/broadcast Your message here"
        )
        return

    groups = await db.active_groups()
    sent = failed = 0
    for group in groups:
        try:
            await context.bot.send_message(group["chat_id"], text)
            sent += 1
        except Exception:
            failed += 1
            await db.deactivate_group(group["chat_id"])

    await update.effective_message.reply_text(
        f"📢 Broadcast completed.\n\n✅ Sent: {sent}\n❌ Failed: {failed}"
    )

async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        return
    count = await db.count_groups()
    await update.effective_message.reply_text(
        f"📊 Statistics\n\n👥 Active Groups: {count}"
    )

async def owner_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        return
    groups = await db.active_groups()
    if not groups:
        await update.effective_message.reply_text("No active groups found.")
        return

    lines = ["👥 Active Groups\n"]
    for i, g in enumerate(groups[:100], 1):
        lines.append(f"{i}. {g.get('title', 'Unknown')} — <code>{g['chat_id']}</code>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
