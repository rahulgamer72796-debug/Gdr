"""Inline-button actions — the whole menu lives here, plus the Google login flow."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import db
from ..drive import (Drive, DriveError, oauth_userinfo, poll_device_token,
                     start_device_login)
from ..logger import log
from ..net import get_http
from ..ui import cards
from ..ui.emoji import t
from ..ui.keyboards import (admin_menu, back_menu, drive_menu, login_link, main_menu, settings_menu, upload_menu)
from ..ui.keyboards import quality_menu
from ..utils import human_size

router = Router(name="callbacks")
LOGIN_STATE: dict[int, dict] = {}      # user_id → {device_code, code, url, expires, msg_id}

EDIT = dict(parse_mode="HTML")


async def _edit(cb: CallbackQuery, text: str, kb=None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb, **EDIT)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            log.debug("edit failed: %s", e)
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════════
#  Google login — OAuth 2.0 Device Flow ("email login")
# ══════════════════════════════════════════════════════════════════════════
async def do_drive_login(message: Message, user_id: int, bot: Optional[Bot] = None,
                        cb_user=None) -> None:
    bot = bot or message.bot
    if not settings.oauth_enabled:
        await message.answer(
            t(f"{cards.emoji('warn')} <b>Email login is switched off on this bot.</b>\n\n"
              f"{cards.emoji('info')} The owner needs to set <code>GDRIVE_CLIENT_ID</code> and "
              f"<code>GDRIVE_CLIENT_SECRET</code> in <code>.env</code> (free, 3 minutes at "
              f"console.cloud.google.com)."),
            parse_mode="HTML")
        return
    try:
        data = await start_device_login(await get_http())
    except DriveError as e:
        await message.answer(f"⚠️ {e}")
        return

    code = data["user_code"]
    url = data.get("verification_url") or "https://www.google.com/device"
    minutes = max(1, int(data.get("expires_in", 1800)) // 60)
    sent = await message.answer(t(cards.login_code(code, url, minutes)), parse_mode="HTML",
                                reply_markup=login_link(url))
    LOGIN_STATE[user_id] = {
        "device_code": data["device_code"], "code": code, "url": url,
        "expires": asyncio.get_event_loop().time() + int(data.get("expires_in", 1800)),
        "msg_id": sent.message_id, "chat_id": sent.chat.id,
        "interval": max(5, int(data.get("interval", 5))),
    }
    asyncio.create_task(_poll_login(user_id, bot, cb_user))


async def _poll_login(user_id: int, bot: Bot, cb_user=None) -> None:
    st = LOGIN_STATE.get(user_id)
    if not st:
        return
    loop = asyncio.get_event_loop()
    while user_id in LOGIN_STATE:
        if loop.time() > st["expires"]:
            LOGIN_STATE.pop(user_id, None)
            await _safe_edit(bot, st, t(f"{cards.emoji('cross')} <b>Login timed out.</b> "
                                        f"Tap “Connect Google Drive” to try again."), None)
            return
        await asyncio.sleep(st["interval"])
        try:
            body = await poll_device_token(await get_http(), st["device_code"])
        except DriveError as e:
            LOGIN_STATE.pop(user_id, None)
            await _safe_edit(bot, st, t(f"{cards.emoji('cross')} {e}"), None)
            return
        if not body:
            continue                      # user hasn't approved yet
        LOGIN_STATE.pop(user_id, None)
        access = body["access_token"]
        refresh = body.get("refresh_token", "")
        expires_at = time.time() + int(body.get("expires_in", 3600))
        info = await oauth_userinfo(await get_http(), access)
        email = info.get("email") or "Google account"
        await db.set_token(user_id, email, access, refresh, expires_at, account="oauth")
        await _safe_edit(bot, st, t(cards.login_success(email)),
                         drive_menu(True, bool(settings.sa_path)))
        log.info("User %s connected Google Drive (%s)", user_id, email)
        try:
            from ..services import logger_channel
            await logger_channel.drive_linked(cb_user, email, "oauth")
        except Exception:  # noqa: BLE001
            pass
        return


async def _safe_edit(bot: Bot, st: dict, text: str, kb) -> None:
    try:
        await bot.edit_message_text(chat_id=st["chat_id"], message_id=st["msg_id"],
                                    text=text, reply_markup=kb, **EDIT)
    except Exception as e:  # noqa: BLE001
        log.debug("login card edit failed: %s", e)


# ══════════════════════════════════════════════════════════════════════════
#  Menu
# ══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data == "menu:home")
async def menu_home(cb: CallbackQuery) -> None:
    name = cb.from_user.first_name or "friend"
    await _edit(cb, t(cards.welcome(name)), main_menu(cb.from_user.id))


@router.callback_query(F.data == "menu:upload")
async def menu_upload(cb: CallbackQuery) -> None:
    await _edit(cb, t(
        f"{cards.emoji('upload')} <b>Upload to Drive</b>\n\n"
        f"{cards.emoji('info')} Send me:\n"
        f"  • a direct link · a YouTube/Insta/TikTok link\n"
        f"  • a Google Drive link (instant clone)\n"
        f"  • or just drop the file in this chat\n\n"
        f"{cards.emoji('bolt')} Everything lands in your connected Drive folder."),
        upload_menu())


@router.callback_query(F.data == "menu:leech")
async def menu_leech(cb: CallbackQuery) -> None:
    await _edit(cb, t(
        f"{cards.emoji('download')} <b>Leech to Telegram</b>\n\n"
        f"Send a link and I'll deliver the file right back here.\n\n"
        f"{cards.emoji('warn')} Cloud Bot API limit: <b>50 MB</b> per file "
        f"(2 GB with a self-hosted local Bot API server).\n"
        f"{cards.emoji('cloud')} Bigger stuff? Use Mirror → Drive."),
        upload_menu())


@router.callback_query(F.data == "menu:drive")
async def menu_drive(cb: CallbackQuery) -> None:
    user = await db.get_user(cb.from_user.id, cb.from_user.username or "",
                             cb.from_user.first_name or "")
    connected = user["drive_mode"] in ("oauth", "sa")
    quota = None
    if connected:
        try:
            drive = Drive(await get_http(), cb.from_user.id, user["drive_mode"])
            about = await drive.about()
            quota = about.get("storageQuota") or {}
            email = (about.get("user") or {}).get("emailAddress", "")
            tok = await db.get_token(cb.from_user.id) or {}
            email = email or tok.get("email", "")
        except DriveError as e:
            await _edit(cb, t(f"{cards.emoji('warn')} {e}"), drive_menu(False, bool(settings.sa_path)))
            return
    else:
        email = ""
    await _edit(cb, t(cards.drive_status(connected, email, user["drive_mode"], quota,
                                         user["folder_name"])),
                drive_menu(connected, bool(settings.sa_path)))


@router.callback_query(F.data == "menu:settings")
async def menu_settings(cb: CallbackQuery) -> None:
    user = await db.get_user(cb.from_user.id)
    await _edit(cb, t(cards.settings_card(user)), settings_menu(user))


@router.callback_query(F.data == "menu:files")
async def menu_files(cb: CallbackQuery) -> None:
    from .files import show_page
    await show_page(cb)


@router.callback_query(F.data == "menu:help")
async def menu_help(cb: CallbackQuery) -> None:
    await _edit(cb, t(cards.help_text()), back_menu())


@router.callback_query(F.data == "menu:admin")
async def menu_admin(cb: CallbackQuery) -> None:
    if cb.from_user.id != settings.owner_id:
        await cb.answer("Owner only.", show_alert=True)
        return
    await _edit(cb, t(f"{cards.emoji('crown')} <b>Admin panel</b>"), admin_menu())


# ══════════════════════════════════════════════════════════════════════════
#  Drive actions
# ══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "drive:login")
async def drive_login(cb: CallbackQuery) -> None:
    await cb.answer()
    if cb.from_user.id in LOGIN_STATE:
        await cb.answer("A login is already in progress…", show_alert=True)
        return
    await do_drive_login(cb.message, cb.from_user.id, cb.bot, cb.from_user)


@router.callback_query(F.data == "drive:verifystart")
async def drive_verify(cb: CallbackQuery) -> None:
    st = LOGIN_STATE.get(cb.from_user.id)
    if not st:
        await cb.answer("No login in progress — tap “Login with Google”.", show_alert=True)
        return
    await _edit(cb, t(cards.login_waiting(st["code"])))
    await cb.answer("Checking with Google…")


@router.callback_query(F.data == "drive:sa")
async def drive_sa(cb: CallbackQuery) -> None:
    if not settings.sa_path:
        await cb.answer("No service account configured.", show_alert=True)
        return
    if not settings.gdrive_folder_id:
        await cb.answer("Owner must set GDRIVE_FOLDER_ID (a folder shared with the "
                        "service account).", show_alert=True)
        return
    await db.update_user(cb.from_user.id, drive_mode="sa", folder_id=settings.gdrive_folder_id,
                         folder_name="Shared Drive folder")
    await cb.answer("Using the bot's Drive ✔")
    await menu_drive(cb)


@router.callback_query(F.data == "drive:logout")
async def drive_logout(cb: CallbackQuery) -> None:
    await db.clear_token(cb.from_user.id)
    await cb.answer("Disconnected ✔")
    await menu_drive(cb)


@router.callback_query(F.data == "drive:test")
async def drive_test(cb: CallbackQuery) -> None:
    user = await db.get_user(cb.from_user.id)
    try:
        drive = Drive(await get_http(), cb.from_user.id, user["drive_mode"])
        about = await drive.about()
        email = (about.get("user") or {}).get("emailAddress", "")
        quota = about.get("storageQuota") or {}
        limit = int(quota.get("limit") or 0)
        usage = int(quota.get("usage") or 0)
        free = human_size(max(0, limit - usage)) if limit else "unlimited"
        await _edit(cb, t(
            f"{cards.emoji('check')} <b>Connection is healthy.</b>\n\n"
            f"{cards.emoji('user')} <code>{email or 'service account'}</code>\n"
            f"{cards.emoji('stats')} Free space: <b>{free}</b>"), drive_menu(True, bool(settings.sa_path)))
    except DriveError as e:
        await _edit(cb, t(f"{cards.emoji('cross')} {e}"), drive_menu(True, bool(settings.sa_path)))


@router.callback_query(F.data == "drive:folder")
async def drive_folder(cb: CallbackQuery) -> None:
    await cb.answer("Send me a folder ID or a Drive folder link — new uploads will go there.",
                    show_alert=True)
    from ..handlers.files import AWAIT_FOLDER
    AWAIT_FOLDER.add(cb.from_user.id)


# ══════════════════════════════════════════════════════════════════════════
#  Task actions
# ══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("task:cancel:"))
async def task_cancel(cb: CallbackQuery) -> None:
    from ..services.tasks import manager
    tid = cb.data.split(":", 2)[2]
    ok = await manager.cancel(tid, by_user=True)
    await cb.answer("Cancelling…" if ok else "Task already finished.", show_alert=not ok)


@router.callback_query(F.data.startswith("leech:go:"))
async def leech_go(cb: CallbackQuery) -> None:
    from ..services.tasks import manager
    uid = cb.data.split(":", 2)[2]
    task = manager.tasks.get(uid)
    if not task:
        await cb.answer("Expired.", show_alert=True)
        return
    task.mode = "leech"
    await cb.answer("Leeching it ✔")
    await _edit(cb, t(f"{cards.emoji('download')} Switched to <b>leech</b> mode."), None)


@router.callback_query(F.data.startswith("leech:no:"))
async def leech_no(cb: CallbackQuery) -> None:
    from ..services.tasks import manager
    uid = cb.data.split(":", 2)[2]
    await manager.cancel(uid, by_user=True)
    await _edit(cb, t(f"{cards.emoji('cross')} Cancelled."), None)


# ══════════════════════════════════════════════════════════════════════════
#  Settings
# ══════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "set:as_doc")
async def set_as_doc(cb: CallbackQuery) -> None:
    user = await db.get_user(cb.from_user.id)
    await db.update_user(cb.from_user.id, as_doc=0 if user["as_doc"] else 1)
    await menu_settings(cb)


@router.callback_query(F.data == "set:thumb")
async def set_thumb(cb: CallbackQuery) -> None:
    user = await db.get_user(cb.from_user.id)
    await db.update_user(cb.from_user.id, thumb=0 if user["thumb"] else 1)
    await menu_settings(cb)


@router.callback_query(F.data == "set:cleanup")
async def set_cleanup(cb: CallbackQuery) -> None:
    user = await db.get_user(cb.from_user.id)
    await db.update_user(cb.from_user.id, cleanup=0 if user["cleanup"] else 1)
    await menu_settings(cb)


@router.callback_query(F.data == "set:quality")
async def set_quality_menu(cb: CallbackQuery) -> None:
    user = await db.get_user(cb.from_user.id)
    await _edit(cb, t(f"{cards.emoji('video')} <b>Pick the default quality</b> for "
                      f"yt-dlp links."), quality_menu(user["quality"]))


@router.callback_query(F.data.startswith("set:quality:"))
async def set_quality(cb: CallbackQuery) -> None:
    q = cb.data.split(":", 2)[2]
    await db.update_user(cb.from_user.id, quality=q)
    user = await db.get_user(cb.from_user.id)
    await _edit(cb, t(cards.settings_card(user)), quality_menu(q))


@router.callback_query(F.data == "set:folder")
async def set_folder(cb: CallbackQuery) -> None:
    from ..handlers.files import AWAIT_FOLDER
    AWAIT_FOLDER.add(cb.from_user.id)
    await cb.answer("Send a Drive folder ID or link.", show_alert=True)
