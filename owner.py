from telegram import Update
from telegram.ext import ContextTypes
from config import OWNER_ID
from database import db
from mtproto_client import mt

def owner_only(update): return bool(update.effective_user and update.effective_user.id==OWNER_ID)

async def owner_start(update,context):
    if not owner_only(update):
        return

    # Send the Owner dashboard first. Do not let an optional MongoDB/settings
    # lookup prevent the Owner from getting any response.
    msg = update.effective_message
    try:
        await msg.reply_text(
            "👑 Bio Link Protector Owner Panel\n\n"
            "👥 Active Groups: loading...\n"
            "🔐 MTProto Account: checking...\n\n"
            "Commands:\n"
            "/mtproto - MTProto account settings\n"
            "/mtlogin - Login / Change MTProto account\n"
            "/mtlogout - Logout MTProto account\n"
            "/broadcast - Broadcast\n"
            "/stats - Statistics\n"
            "/groups - Groups"
        )
    except Exception:
        # Let the application logger report Telegram send failures.
        raise

    # Update the dashboard with live values when MongoDB is available.
    try:
        groups = await db.count_groups()
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Owner dashboard group count failed: %s", e)
        groups = 0

    try:
        acc = await db.get_mt_account()
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Owner dashboard MTProto status failed: %s", e)
        acc = None

    status = (
        f"🟢 Connected\n📱 {acc.get('phone','Unknown')}"
        if acc and acc.get("connected")
        else "🔴 Not connected"
    )

    try:
        await msg.reply_text(
            "👑 Bio Link Protector Owner Panel\n\n"
            f"👥 Active Groups: {groups}\n"
            f"🔐 MTProto Account: {status}\n\n"
            "Commands:\n"
            "/mtproto - MTProto account settings\n"
            "/mtlogin - Login / Change account\n"
            "/mtlogout - Logout\n"
            "/broadcast - Broadcast\n"
            "/stats - Statistics\n"
            "/groups - Groups"
        )
    except Exception:
        raise

async def mtproto_menu(update,context):
    if not owner_only(update): return
    acc=await db.get_mt_account()
    if acc and acc.get("connected"):
        await update.effective_message.reply_text(
            f"🔐 MTProto Account\n\n🟢 Connected\n📱 {acc.get('phone','Unknown')}\n"
            f"👤 @{acc.get('username') or 'No username'}\n\n"
            "/mtlogin - Login / Change account\n/mtlogout - Logout")
    else:
        await update.effective_message.reply_text("🔐 MTProto Account\n\n🔴 Not connected\n\nUse /mtlogin to connect.")

async def mtlogin(update,context):
    if not owner_only(update):return
    context.user_data["mt_state"]="phone"
    await update.effective_message.reply_text("📱 Send Telegram phone number with country code.\nExample: +919876543210\n\n/cancel to cancel.")

async def mtlogout(update,context):
    if not owner_only(update):return
    try:
        await mt.logout(); context.user_data.clear()
        await update.effective_message.reply_text("✅ MTProto account logged out.")
    except Exception as e: await update.effective_message.reply_text(f"❌ Logout failed: {str(e)[:300]}")

async def mtlogin_message(update,context):
    if not owner_only(update):return
    state=context.user_data.get("mt_state")
    if not state:return
    text=(update.effective_message.text or "").strip()
    if text=="/cancel":
        context.user_data.clear(); await update.effective_message.reply_text("❌ Login cancelled."); return
    try:
        if state=="phone":
            await mt.login_send_code(text); context.user_data["mt_phone"]=text; context.user_data["mt_state"]="code"
            await update.effective_message.reply_text("📨 Enter the Telegram login code.")
        elif state=="code":
            me,needs2fa=await mt.login_code(text)
            if needs2fa:
                context.user_data["mt_state"]="password"; await update.effective_message.reply_text("🔐 Enter your 2FA password.")
            else:
                await mt.finish_login(context.user_data["mt_phone"],me); context.user_data.clear()
                await update.effective_message.reply_text("✅ MTProto account connected successfully.")
        elif state=="password":
            me=await mt.login_password(text); await mt.finish_login(context.user_data["mt_phone"],me)
            context.user_data.clear(); await update.effective_message.reply_text("✅ MTProto account connected successfully.")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Login failed: {str(e)[:300]}")

async def owner_broadcast(update,context):
    if not owner_only(update):return
    text=update.effective_message.text.partition(" ")[2].strip()
    if not text: await update.effective_message.reply_text("Usage: /broadcast Your message here"); return
    groups=await db.active_groups(); sent=failed=0
    for g in groups:
        try: await context.bot.send_message(g["chat_id"],text);sent+=1
        except: failed+=1;await db.deactivate_group(g["chat_id"])
    await update.effective_message.reply_text(f"📢 Broadcast completed.\n\n✅ Sent: {sent}\n❌ Failed: {failed}")

async def owner_stats(update,context):
    if owner_only(update): await update.effective_message.reply_text(f"📊 Statistics\n\n👥 Active Groups: {await db.count_groups()}")

async def owner_groups(update,context):
    if not owner_only(update):return
    groups=await db.active_groups()
    if not groups: await update.effective_message.reply_text("No active groups found.");return
    await update.effective_message.reply_text("\n".join(["👥 Active Groups\n"]+[f"{i}. {g.get('title','Unknown')} — <code>{g['chat_id']}</code>" for i,g in enumerate(groups[:100],1)]),parse_mode="HTML")
