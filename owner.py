import asyncio
import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import OWNER_ID, DATABASE_NAME
from database import db
from mtproto_client import mt

logger = logging.getLogger(__name__)


async def _user_groups(update, context):
    user = update.effective_user
    if not user:
        return []
    groups = await db.active_groups()
    result = []
    for group in groups:
        try:
            member = await context.bot.get_chat_member(int(group["chat_id"]), int(user.id))
            if member.status in ("administrator", "creator"):
                result.append(group)
        except Exception:
            continue
    return result

async def user_dashboard(update, context):
    if not update.effective_user or update.effective_user.id == OWNER_ID:
        return
    groups = await _user_groups(update, context)
    keyboard = []
    for group in groups[:20]:
        title = (group.get("title") or str(group.get("chat_id")))[:35]
        keyboard.append([InlineKeyboardButton(f"👥 {title}", callback_data=f"user:group:{group['chat_id']}")])
    text = (
        "🛡️ <b>Bio Link Protector</b>\n\n"
        "Select your group below to configure bio-link protection settings."
    )
    if not groups:
        text += "\n\n<i>No groups found where you are an administrator.</i>"
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

async def _verify_group_admin(query, context, chat_id):
    try:
        member = await context.bot.get_chat_member(int(chat_id), int(query.from_user.id))
        return member.status in ("administrator", "creator")
    except Exception:
        return False

def _group_settings_keyboard(chat_id, settings):
    join = "🟢 ON" if settings.get("detect_on_join", True) else "🔴 OFF"
    action = "🚫 Punish" if settings.get("message_action", "punish") == "punish" else "⚠️ Warning"
    delete = "🟢 ON" if settings.get("delete_after_warning", True) else "🔴 OFF"
    punishment = "🔨 Ban" if settings.get("punishment", "ban") == "ban" else "🔇 Mute"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔎 Detect on Join: {join}", callback_data=f"user:set:{chat_id}:join")],
        [InlineKeyboardButton(f"💬 Message Action: {action}", callback_data=f"user:set:{chat_id}:message")],
        [InlineKeyboardButton(f"🗑️ Delete after Warning: {delete}", callback_data=f"user:set:{chat_id}:delete")],
        [InlineKeyboardButton(f"⚖️ Punishment: {punishment}", callback_data=f"user:set:{chat_id}:punishment")],
        [InlineKeyboardButton("⬅️ My Groups", callback_data="user:home")],
    ])

async def _show_group_settings(query, context, chat_id):
    if not await _verify_group_admin(query, context, chat_id):
        await query.answer("You must be a group administrator to change settings.", show_alert=True)
        return
    group = await db.get_group(int(chat_id))
    if not group:
        await query.answer("Group not found.", show_alert=True)
        return
    settings = await db.get_group_settings(int(chat_id))
    title = escape(group.get("title") or str(chat_id))
    text = (
        f"⚙️ <b>{title}</b>\n\n"
        "Configure when the bio is checked and what action is taken.\n\n"
        f"🔎 Detect on Join: <b>{'ON' if settings.get('detect_on_join', True) else 'OFF'}</b>\n"
        f"💬 Message Action: <b>{'Punish' if settings.get('message_action') == 'punish' else 'Warning'}</b>\n"
        f"🗑️ Delete after Warning: <b>{'ON' if settings.get('delete_after_warning', True) else 'OFF'}</b>\n"
        f"⚖️ Punishment: <b>{'Ban' if settings.get('punishment') == 'ban' else 'Mute'}</b>"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=_group_settings_keyboard(chat_id, settings))
    await query.answer()

async def user_callback(update, context):
    query = update.callback_query
    if not query or query.from_user.id == OWNER_ID:
        return
    data = query.data or ""
    if data == "user:home":
        await query.answer()
        groups = await _user_groups(update, context)
        keyboard = [[InlineKeyboardButton(f"👥 {(g.get('title') or str(g.get('chat_id')))[:35]}", callback_data=f"user:group:{g['chat_id']}")] for g in groups[:20]]
        text = "🛡️ <b>Bio Link Protector</b>\n\nSelect your group below to configure bio-link protection settings."
        if not groups:
            text += "\n\n<i>No groups found where you are an administrator.</i>"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
        return
    if data.startswith("user:group:"):
        chat_id = int(data.rsplit(":",1)[1])
        await _show_group_settings(query, context, chat_id)
        return
    if data.startswith("user:set:"):
        _, _, chat_id_raw, key = data.split(":")
        chat_id = int(chat_id_raw)
        if not await _verify_group_admin(query, context, chat_id):
            await query.answer("You must be a group administrator.", show_alert=True)
            return
        settings = await db.get_group_settings(chat_id)
        if key == "join":
            await db.set_group_setting(chat_id, "detect_on_join", not settings.get("detect_on_join", True))
        elif key == "message":
            await db.set_group_setting(chat_id, "message_action", "warn" if settings.get("message_action", "punish") == "punish" else "punish")
        elif key == "delete":
            await db.set_group_setting(chat_id, "delete_after_warning", not settings.get("delete_after_warning", True))
        elif key == "punishment":
            await db.set_group_setting(chat_id, "punishment", "mute" if settings.get("punishment", "ban") == "ban" else "ban")
        await _show_group_settings(query, context, chat_id)
        return

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
    context.user_data.pop("broadcast_items", None)
    context.user_data.pop("broadcast_media_group_id", None)
    context.user_data.pop("broadcast_collect_task", None)
    await update.effective_message.reply_text(
        "📢 <b>Broadcast</b>\n\n"
        "Send up to <b>10 media items</b> as one album, or send a text message.\n"
        "Supported: photo, video, document/file, audio, voice, animation and text.\n"
        "Captions are preserved. The same broadcast will be sent to <b>all active groups</b> and <b>all users who started the bot</b>.\n\n"
        "After sending the media/message, you will get a <b>Confirm / Cancel</b> button.\n\n"
        "Send <code>/cancel</code> to cancel.", parse_mode="HTML"
    )


async def _finish_broadcast_collection(update, context):
    """Finalize a media album after Telegram has delivered its messages."""
    await asyncio.sleep(1.2)
    if not context.user_data.get("broadcast_mode"):
        return
    items = context.user_data.get("broadcast_items") or []
    if not items:
        return

    # Keep first 10 messages only. Telegram media groups are max 10.
    items = items[:10]
    context.user_data["broadcast_items"] = items
    context.user_data["broadcast_chat_id"] = update.effective_chat.id
    context.user_data["broadcast_mode"] = False
    context.user_data.pop("broadcast_collect_task", None)

    kind = "media album" if len(items) > 1 else "media/message"
    await update.effective_message.reply_text(
        "📢 <b>Broadcast Preview Ready</b>\n\n"
        f"📦 <b>{len(items)}</b> item(s) in this {kind}.\n"
        "📍 <b>Recipients:</b> all active groups + all users who started the bot.\n"
        "📝 Captions will be preserved.\n\n"
        "Do you want to send this broadcast?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Broadcast", callback_data="owner:broadcast_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="owner:broadcast_cancel")],
        ])
    )


async def owner_broadcast_message(update, context):
    if not owner_only(update) or not context.user_data.get("broadcast_mode"):
        return False
    msg = update.effective_message
    if not msg:
        return False

    if msg.text and msg.text.strip() == "/cancel":
        task = context.user_data.pop("broadcast_collect_task", None)
        if task:
            task.cancel()
        context.user_data.pop("broadcast_mode", None)
        context.user_data.pop("broadcast_items", None)
        context.user_data.pop("broadcast_media_group_id", None)
        await msg.reply_text("❌ Broadcast cancelled.")
        await owner_start(update, context)
        return True

    supported = bool(msg.text or msg.photo or msg.video or msg.document or msg.audio or msg.voice or msg.animation)
    if not supported:
        await msg.reply_text("⚠️ Please send text or supported media. You can send up to 10 media items as one album.")
        return True

    # A Telegram media album arrives as several updates with the same media_group_id.
    media_group_id = getattr(msg, "media_group_id", None)
    if media_group_id:
        current_group = context.user_data.get("broadcast_media_group_id")
        if current_group and current_group != media_group_id:
            await msg.reply_text("⚠️ Please finish the current broadcast album first, or cancel it.")
            return True
        context.user_data["broadcast_media_group_id"] = media_group_id
        items = context.user_data.setdefault("broadcast_items", [])
        if msg.message_id not in items:
            if len(items) < 10:
                items.append(msg.message_id)
            else:
                return True

        old_task = context.user_data.get("broadcast_collect_task")
        if old_task:
            old_task.cancel()
        task = asyncio.create_task(_finish_broadcast_collection(update, context))
        context.user_data["broadcast_collect_task"] = task
        return True

    # Plain text or a single media item: finalize shortly after the message arrives.
    context.user_data["broadcast_items"] = [msg.message_id]
    context.user_data["broadcast_chat_id"] = msg.chat_id
    context.user_data["broadcast_mode"] = False
    await msg.reply_text(
        "📢 <b>Broadcast Preview Ready</b>\n\n"
        "📍 <b>Recipients:</b> all active groups + all users who started the bot.\n"
        "📝 Caption will be preserved when present.\n\n"
        "Do you want to send this broadcast?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Broadcast", callback_data="owner:broadcast_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="owner:broadcast_cancel")],
        ])
    )
    return True


async def _copy_to_target(context, source_chat_id, message_ids, target_chat_id):
    """Copy one text/media message or an album to one target."""
    if len(message_ids) == 1:
        await context.bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=source_chat_id,
            message_id=message_ids[0],
        )
    else:
        # Bot API copyMessages preserves the original media/captions and copies
        # the complete album in one operation. Max 10 is enforced above.
        await context.bot.copy_messages(
            chat_id=target_chat_id,
            from_chat_id=source_chat_id,
            message_ids=message_ids,
        )


async def _do_broadcast(update, context):
    query = update.callback_query
    message_ids = list(context.user_data.get("broadcast_items") or [])
    source_chat_id = context.user_data.get("broadcast_chat_id") or query.message.chat_id
    if not message_ids or not source_chat_id:
        await query.answer("Broadcast data expired. Please start again.", show_alert=True)
        return

    groups = await db.active_groups()
    users = await db.active_users()
    targets = [int(g["chat_id"]) for g in groups]
    targets += [int(u["_id"]) for u in users]
    # Deduplicate while preserving order.
    targets = list(dict.fromkeys(targets))

    sent = failed = 0
    failed_groups = 0
    failed_users = 0

    sem = asyncio.Semaphore(15)

    async def send_one(target):
        nonlocal sent, failed, failed_groups, failed_users
        async with sem:
            try:
                await _copy_to_target(context, source_chat_id, message_ids, target)
                sent += 1
            except Exception as exc:
                failed += 1
                if target < 0:
                    failed_groups += 1
                    try:
                        await db.deactivate_group(target)
                    except Exception:
                        pass
                else:
                    failed_users += 1
                    # A blocked/deleted user should not be retried forever.
                    try:
                        await db.deactivate_user(target)
                    except Exception:
                        pass
                logger.warning("Broadcast failed target=%s: %s", target, exc)

    await asyncio.gather(*(send_one(target) for target in targets))

    for key in ("broadcast_items", "broadcast_chat_id", "broadcast_mode", "broadcast_media_group_id", "broadcast_collect_task"):
        context.user_data.pop(key, None)

    await query.answer("Broadcast completed")
    await query.message.reply_text(
        "📢 <b>Broadcast completed</b>\n\n"
        f"📦 Items: <b>{len(message_ids)}</b>\n"
        f"👥 Groups: <b>{len(groups)}</b>\n"
        f"👤 Users: <b>{len(users)}</b>\n"
        f"✅ Delivered: <b>{sent}</b>\n"
        f"❌ Failed: <b>{failed}</b>\n"
        f"   • Groups failed: {failed_groups}\n"
        f"   • Users failed: {failed_users}",
        parse_mode="HTML",
    )
    await _show_dashboard(query, context)

async def owner_stats(update, context):
    if not owner_only(update):
        return
    stats = await db.get_statistics()
    text = (
        "📊 <b>Statistics</b>\n\n"
        f"👥 Groups: <b>{stats['groups']}</b>\n"
        f"▶️ Bot Users: <b>{stats['users_started']}</b>\n"
        f"🚫 Users Banned: <b>{stats['users_banned']}</b>\n"
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
        context.user_data.pop("broadcast_items", None)
        context.user_data.pop("broadcast_media_group_id", None)
        await query.message.reply_text(
            "📢 <b>Broadcast</b>\n\nSend text or up to <b>10 media items</b> as one album.\n"
            "Supported: photo, video, document/file, audio, voice and animation.\n"
            "Caption is preserved.\n\n/cancel to cancel.", parse_mode="HTML"
        )
        return

    if data == "owner:broadcast_confirm":
        await _do_broadcast(update, context)
        return

    if data == "owner:broadcast_cancel":
        task = context.user_data.pop("broadcast_collect_task", None)
        if task:
            task.cancel()
        context.user_data.pop("broadcast_items", None)
        context.user_data.pop("broadcast_chat_id", None)
        context.user_data.pop("broadcast_mode", None)
        context.user_data.pop("broadcast_media_group_id", None)
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
