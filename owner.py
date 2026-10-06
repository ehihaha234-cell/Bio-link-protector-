import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import OWNER_ID, DATABASE_NAME
from database import db
from mtproto_client import mt

logger = logging.getLogger(__name__)


def owner_only(update):
    return bool(update.effective_user and update.effective_user.id == OWNER_ID)


def _dashboard_keyboard(connected: bool):
    detector = "🔌 Disconnect Detector Account" if connected else "📡 Add Detector Account"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(detector, callback_data="owner:detector")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="owner:broadcast")],
        [InlineKeyboardButton("📊 Statistics", callback_data="owner:stats")],
        [InlineKeyboardButton("👥 Active Groups", callback_data="owner:groups:0")],
    ])


async def _dashboard_text():
    try:
        groups = await db.count_groups()
    except Exception as exc:
        logger.exception("Owner dashboard group count failed (db=%s): %s", DATABASE_NAME, exc)
        groups = 0

    try:
        acc = await db.get_mt_account()
    except Exception as exc:
        logger.exception("Owner dashboard MTProto status failed (db=%s): %s", DATABASE_NAME, exc)
        acc = None

    connected = bool(acc and acc.get("connected") and acc.get("session"))
    if connected:
        status = f"🟢 Connected\n📱 {escape(acc.get('phone') or 'Unknown')}"
    else:
        status = "🔴 Not connected"

    text = (
        "👑 <b>Bio Link Protector Owner Panel</b>\n\n"
        f"👥 <b>Active Groups:</b> {groups}\n"
        f"🔐 <b>Detector Account:</b> {status}\n\n"
        "<i>Select an option below:</i>"
    )
    return text, connected


async def owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        return
    text, connected = await _dashboard_text()
    await update.effective_message.reply_text(
        text, parse_mode="HTML", reply_markup=_dashboard_keyboard(connected)
    )


async def _show_dashboard(target, context):
    text, connected = await _dashboard_text()
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(text, parse_mode="HTML", reply_markup=_dashboard_keyboard(connected))
    else:
        await target.reply_text(text, parse_mode="HTML", reply_markup=_dashboard_keyboard(connected))


async def mtproto_menu(update, context):
    if not owner_only(update):
        return
    acc = await db.get_mt_account()
    if acc and acc.get("connected"):
        await update.effective_message.reply_text(
            f"🔐 Detector Account\n\n🟢 <b>Connected</b>\n📱 {escape(acc.get('phone','Unknown'))}\n"
            f"👤 @{escape(acc.get('username') or 'No username')}\n\nUse the Owner Panel button to disconnect or change the account.",
            parse_mode="HTML", reply_markup=_dashboard_keyboard(True)
        )
    else:
        await update.effective_message.reply_text(
            "🔐 <b>Detector Account</b>\n\n🔴 Not connected\n\nUse <b>Add Detector Account</b> to connect it.",
            parse_mode="HTML", reply_markup=_dashboard_keyboard(False)
        )


async def mtlogin(update, context):
    if not owner_only(update):
        return
    context.user_data["mt_state"] = "phone"
    await update.effective_message.reply_text(
        "📡 <b>Add Detector Account</b>\n\n"
        "Send the Telegram phone number with country code.\n"
        "Example: <code>+919876543210</code>\n\n"
        "/cancel to cancel.", parse_mode="HTML"
    )


async def mtlogout(update, context):
    if not owner_only(update):
        return
    try:
        await mt.logout()
        context.user_data.pop("mt_state", None)
        await update.effective_message.reply_text("✅ Detector account disconnected.")
        await owner_start(update, context)
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ Disconnect failed: {str(exc)[:300]}")


async def mtlogin_message(update, context):
    if not owner_only(update):
        return False
    state = context.user_data.get("mt_state")
    if not state:
        return False
    text = (update.effective_message.text or "").strip()
    if text == "/cancel":
        context.user_data.pop("mt_state", None)
        await update.effective_message.reply_text("❌ Detector account setup cancelled.")
        await owner_start(update, context)
        return True
    try:
        if state == "phone":
            await mt.login_send_code(text)
            context.user_data["mt_phone"] = text
            context.user_data["mt_state"] = "code"
            await update.effective_message.reply_text("📨 Enter the Telegram login code.")
        elif state == "code":
            me, needs2fa = await mt.login_code(text)
            if needs2fa:
                context.user_data["mt_state"] = "password"
                await update.effective_message.reply_text("🔐 Enter your Telegram 2FA password.")
            else:
                await mt.finish_login(context.user_data["mt_phone"], me)
                context.user_data.clear()
                await update.effective_message.reply_text("✅ Detector account connected successfully.")
                await owner_start(update, context)
        elif state == "password":
            me = await mt.login_password(text)
            await mt.finish_login(context.user_data["mt_phone"], me)
            context.user_data.clear()
            await update.effective_message.reply_text("✅ Detector account connected successfully.")
            await owner_start(update, context)
        return True
    except Exception as exc:
        logger.exception("Detector login failed")
        await update.effective_message.reply_text(f"❌ Login failed: {str(exc)[:400]}")
        return True


async def owner_broadcast(update, context):
    if not owner_only(update):
        return
    context.user_data["broadcast_mode"] = True
    await update.effective_message.reply_text(
        "📢 <b>Broadcast</b>\n\n"
        "Send the message or media you want to broadcast.\n"
        "Supported: text, photo, video, document/file, audio and voice.\n"
        "Caption will be included when media has a caption.\n\n"
        "Send <code>/cancel</code> to cancel.", parse_mode="HTML"
    )


async def owner_broadcast_message(update, context):
    if not owner_only(update) or not context.user_data.get("broadcast_mode"):
        return False
    msg = update.effective_message
    if not msg:
        return False
    if msg.text and msg.text.strip() == "/cancel":
        context.user_data.pop("broadcast_mode", None)
        await msg.reply_text("❌ Broadcast cancelled.")
        await owner_start(update, context)
        return True

    if not (msg.text or msg.photo or msg.video or msg.document or msg.audio or msg.voice or msg.animation):
        await msg.reply_text("⚠️ Please send text, photo, video, file, audio or voice message.")
        return True

    context.user_data["broadcast_message_id"] = msg.message_id
    context.user_data["broadcast_chat_id"] = msg.chat_id
    context.user_data["broadcast_mode"] = False

    await msg.reply_text(
        "📢 <b>Broadcast Preview Ready</b>\n\n"
        "The message/media above will be sent to all active groups.\n\n"
        "Are you sure you want to broadcast it?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Broadcast", callback_data="owner:broadcast_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="owner:broadcast_cancel")],
        ])
    )
    return True


async def _do_broadcast(update, context):
    message_id = context.user_data.get("broadcast_message_id")
    source_chat_id = context.user_data.get("broadcast_chat_id")
    if not message_id or not source_chat_id:
        await update.callback_query.answer("Broadcast data expired. Please start again.", show_alert=True)
        return

    groups = await db.active_groups()
    sent = failed = 0
    for group in groups:
        try:
            await context.bot.copy_message(
                chat_id=group["chat_id"],
                from_chat_id=source_chat_id,
                message_id=message_id,
            )
            sent += 1
        except Exception:
            failed += 1
            try:
                await db.deactivate_group(group["chat_id"])
            except Exception:
                pass

    context.user_data.pop("broadcast_message_id", None)
    context.user_data.pop("broadcast_chat_id", None)
    await update.callback_query.answer("Broadcast completed")
    await update.callback_query.message.reply_text(
        f"📢 <b>Broadcast completed</b>\n\n✅ Sent: {sent}\n❌ Failed: {failed}",
        parse_mode="HTML",
    )
    await _show_dashboard(update.callback_query, context)


async def owner_stats(update, context):
    if not owner_only(update):
        return
    stats = await db.get_statistics()
    text = (
        "📊 <b>Statistics</b>\n\n"
        f"👥 Groups: <b>{stats['groups']}</b>\n"
        f"▶️ Users started bot: <b>{stats['users_started']}</b>\n"
        f"🚫 Users banned: <b>{stats['users_banned']}</b>\n"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Owner Dashboard", callback_data="owner:home")]])
        )
        await update.callback_query.answer()
    else:
        await update.effective_message.reply_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Owner Dashboard", callback_data="owner:home")]])
        )


async def _groups_page(update, context, page=0):
    groups = await db.active_groups()
    per_page = 10
    total_pages = max(1, (len(groups) + per_page - 1) // per_page)
    page = max(0, min(int(page), total_pages - 1))
    chunk = groups[page * per_page:(page + 1) * per_page]

    keyboard = []
    for group in chunk:
        title = (group.get("title") or str(group.get("chat_id")))[:28]
        paused = bool(group.get("paused", False))
        state = "▶️ Resume" if paused else "⏸ Pause"
        keyboard.append([
            InlineKeyboardButton(f"👥 {title}", callback_data=f"owner:group:{group['chat_id']}:{page}"),
            InlineKeyboardButton(state, callback_data=f"owner:pause:{group['chat_id']}:{0 if paused else 1}:{page}"),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"owner:groups:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"owner:groups:{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("⬅️ Owner Dashboard", callback_data="owner:home")])

    text = (
        "👥 <b>Active Groups</b>\n\n"
        f"Showing {page * per_page + 1 if chunk else 0}-{page * per_page + len(chunk)} of {len(groups)}\n\n"
        "⏸ Paused groups remain registered but protection is temporarily disabled."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        await update.callback_query.answer()
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def owner_groups(update, context):
    if not owner_only(update):
        return
    await _groups_page(update, context, 0)


async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not owner_only(update):
        return
    data = query.data or ""

    if data == "owner:home":
        await query.answer()
        await _show_dashboard(query, context)
        return

    if data == "owner:detector":
        acc = await db.get_mt_account()
        if acc and acc.get("connected"):
            try:
                await mt.logout()
                await query.answer("Detector account disconnected")
                await _show_dashboard(query, context)
            except Exception as exc:
                await query.answer("Disconnect failed", show_alert=True)
                await query.message.reply_text(f"❌ Disconnect failed: {str(exc)[:300]}")
        else:
            await query.answer()
            context.user_data["mt_state"] = "phone"
            await query.message.reply_text(
                "📡 <b>Add Detector Account</b>\n\n"
                "Send Telegram phone number with country code.\n"
                "Example: <code>+919876543210</code>\n\n"
                "/cancel to cancel.", parse_mode="HTML"
            )
        return

    if data == "owner:broadcast":
        await query.answer()
        context.user_data["broadcast_mode"] = True
        await query.message.reply_text(
            "📢 <b>Broadcast</b>\n\nSend text or media (photo/video/file/audio/voice).\n"
            "Caption is preserved.\n\n/cancel to cancel.", parse_mode="HTML"
        )
        return

    if data == "owner:broadcast_confirm":
        await _do_broadcast(update, context)
        return

    if data == "owner:broadcast_cancel":
        context.user_data.pop("broadcast_message_id", None)
        context.user_data.pop("broadcast_chat_id", None)
        context.user_data.pop("broadcast_mode", None)
        await query.answer("Broadcast cancelled")
        await _show_dashboard(query, context)
        return

    if data == "owner:stats":
        await owner_stats(update, context)
        return

    if data.startswith("owner:groups:"):
        await _groups_page(update, context, int(data.rsplit(":", 1)[1]))
        return

    if data.startswith("owner:pause:"):
        _, _, chat_id, paused, page = data.split(":")
        await db.set_group_paused(int(chat_id), bool(int(paused)))
        await query.answer("Group resumed" if not int(paused) else "Group paused")
        await _groups_page(update, context, int(page))
        return

    if data.startswith("owner:group:"):
        _, _, chat_id_raw, page_raw = data.split(":")
        chat_id = int(chat_id_raw)
        page = int(page_raw)
        group = await db.get_group(chat_id)
        if not group:
            await query.answer("Group not found", show_alert=True)
            return
        paused = bool(group.get("paused", False))
        text = (
            f"👥 <b>{escape(group.get('title') or 'Unknown Group')}</b>\n\n"
            f"🆔 <code>{chat_id}</code>\n"
            f"📌 Status: {'⏸ Paused' if paused else '🟢 Protected'}"
        )
        keyboard = [[InlineKeyboardButton("▶️ Resume" if paused else "⏸ Pause", callback_data=f"owner:pause:{chat_id}:{0 if paused else 1}:{page}")],
                    [InlineKeyboardButton("⬅️ Active Groups", callback_data=f"owner:groups:{page}")]]
        await query.answer()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
