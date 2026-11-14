"""Commands: /start /help /login /logout /status /cancel /settings /files /id /ping /about."""
from __future__ import annotations

import time

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from ..config import settings
from ..db import db
from ..ui import cards
from ..ui.emoji import t
from ..ui.keyboards import drive_menu, main_menu
from ..utils import clip

router = Router(name="commands")
BOOT_TIME = time.time()


@router.message(CommandStart(deep_link=True))
async def start_deep(msg: Message, command: CommandStart) -> None:
    """Deep link support: t.me/bot?start=mirror_<base64url link> (shareable mirror links)."""
    import base64
    arg = (command.args or "").strip()
    await _register(msg)
    if arg.startswith("m_"):
        try:
            url = base64.urlsafe_b64decode(arg[2:] + "===").decode()
        except Exception:  # noqa: BLE001
            url = ""
        if url:
            from .upload import start_task_for_url
            await start_task_for_url(msg, url, mode="mirror")
            return
    await msg.answer(t(cards.welcome(msg.from_user.first_name or "friend")), parse_mode="HTML",
                     reply_markup=main_menu(msg.from_user.id))


@router.message(CommandStart())
async def start(msg: Message) -> None:
    await _register(msg)
    await msg.answer(t(cards.welcome(msg.from_user.first_name or "friend")), parse_mode="HTML",
                     reply_markup=main_menu(msg.from_user.id))


async def _register(msg: Message) -> None:
    """Create the user row if new; tell the log channel only on a first visit."""
    u = msg.from_user
    row = await db.get_user(u.id, u.username or "", u.first_name or "")
    # a brand-new row has created_at within the last few seconds
    is_new = (time.time() - float(row.get("created_at") or 0)) < 10
    if is_new:
        from ..services import logger_channel
        await logger_channel.new_user(u, is_new=True)


@router.message(Command("help"))
async def help_cmd(msg: Message) -> None:
    await msg.answer(t(cards.help_text()), parse_mode="HTML",
                     reply_markup=main_menu(msg.from_user.id), disable_web_page_preview=True)


@router.message(Command("id"))
async def id_cmd(msg: Message) -> None:
    await msg.answer(t(f"{cards.emoji('user')} Your id: <code>{msg.from_user.id}</code>\n"
                       f"Chat id: <code>{msg.chat.id}</code>"), parse_mode="HTML")


@router.message(Command("ping"))
async def ping_cmd(msg: Message) -> None:
    t0 = time.perf_counter()
    sent = await msg.answer("🏓 …")
    ms = (time.perf_counter() - t0) * 1000
    up = time.time() - BOOT_TIME
    await sent.edit_text(t(f"{cards.emoji('bolt')} <b>Pong!</b> {ms:.0f} ms\n"
                           f"{cards.emoji('clock')} Uptime: {up / 3600:.1f} h"), parse_mode="HTML")


@router.message(Command("about"))
async def about_cmd(msg: Message) -> None:
    await msg.answer(t(
        f"{cards.emoji('bot')} <b>{settings.bot_name}</b>\n\n"
        f"{cards.emoji('rocket')} Mirror anything → Google Drive, leech back to Telegram.\n"
        f"{cards.emoji('shield')} Email/OAuth login · Service-account mode · resumable uploads\n"
        f"{cards.emoji('star')} Premium emoji: <b>{'on' if cards.emoji.custom else 'fallback'}</b>\n\n"
        f"{cards.emoji('heart')} Built for {settings.bot_username or 'you'} · inspired by MLTB"
    ), parse_mode="HTML", reply_markup=main_menu(msg.from_user.id))


# ── drive login ────────────────────────────────────────────────────────────
@router.message(Command("login", "connect"))
async def login_cmd(msg: Message) -> None:
    from ..handlers.callbacks import do_drive_login
    user = await db.get_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    if user["drive_mode"] == "oauth":
        tok = await db.get_token(msg.from_user.id) or {}
        await msg.answer(t(cards.drive_status(True, tok.get("email", ""), "oauth",
                                              folder=user["folder_name"])),
                         parse_mode="HTML", reply_markup=drive_menu(True, bool(settings.sa_path)))
        return
    await do_drive_login(msg, msg.from_user.id)


@router.message(Command("logout"))
async def logout_cmd(msg: Message) -> None:
    await db.clear_token(msg.from_user.id)
    await msg.answer(t(f"{cards.emoji('logout')} Google account disconnected."),
                     parse_mode="HTML", reply_markup=main_menu(msg.from_user.id))


@router.message(Command("drive"))
async def drive_cmd(msg: Message) -> None:
    user = await db.get_user(msg.from_user.id)
    connected = user["drive_mode"] in ("oauth", "sa")
    await msg.answer(t(cards.drive_status(connected, mode=user["drive_mode"],
                                          folder=user["folder_name"])),
                     parse_mode="HTML", reply_markup=drive_menu(connected, bool(settings.sa_path)))


# ── task control ───────────────────────────────────────────────────────────
@router.message(Command("status"))
async def status_cmd(msg: Message) -> None:
    from ..services.tasks import manager
    tasks = manager.active_for_user(msg.from_user.id)
    await msg.answer(t(cards.status_list(tasks)), parse_mode="HTML")


@router.message(Command("cancel"))
async def cancel_cmd(msg: Message, command: CommandObject) -> None:
    from ..services.tasks import manager
    arg = (command.args or "").strip()
    active = manager.active_for_user(msg.from_user.id)
    if arg:
        target = next((t_ for t_ in active if t_.id.startswith(arg)), None)
        if not target:
            await msg.answer("No matching task.")
            return
        await manager.cancel(target.id, by_user=True)
        await msg.answer("🛑 Cancelling…")
        return
    if not active:
        await msg.answer(t(f"{cards.emoji('info')} No active tasks."), parse_mode="HTML")
        return
    if len(active) == 1:
        await manager.cancel(active[0].id, by_user=True)
        await msg.answer("🛑 Cancelling…")
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from ..ui.keyboards import btn
    kb = InlineKeyboardBuilder()
    for t_ in active:
        kb.row(btn(f"✖ {clip(t_.name or t_.display_source, 34)}", f"task:cancel:{t_.id}"))
    await msg.answer("Which one?", reply_markup=kb.as_markup())


@router.message(Command("settings", "usettings"))
async def settings_cmd(msg: Message) -> None:
    from ..ui.keyboards import settings_menu
    user = await db.get_user(msg.from_user.id)
    await msg.answer(t(cards.settings_card(user)), parse_mode="HTML",
                     reply_markup=settings_menu(user))


@router.message(Command("audio", "ytdl", "watch"))
async def audio_cmd(msg: Message, command: CommandObject) -> None:
    """Download audio from any media link (mp3/m4a) — for music channels."""
    from .upload import start_task_for_url
    url = (command.args or "").strip()
    if not url:
        await msg.answer(t(f"{cards.emoji('audio')} <b>Usage:</b> "
                           f"<code>/audio https://youtu.be/…</code>"), parse_mode="HTML")
        return
    user = await db.get_user(msg.from_user.id)
    await db.update_user(msg.from_user.id, quality="audio")
    await start_task_for_url(msg, url, mode="mirror" if user["drive_mode"] != "none" else "leech")
    await db.update_user(msg.from_user.id, quality=user["quality"])


@router.message(Command("mystats", "me", "usage"))
async def mystats_cmd(msg: Message) -> None:
    """Every user can see their own upload history — nothing about others."""
    user = await db.get_user(msg.from_user.id, msg.from_user.username or "",
                             msg.from_user.first_name or "")
    ustats = await db.user_stats(msg.from_user.id)
    await msg.answer(t(cards.user_profile(user, ustats)), parse_mode="HTML",
                     reply_markup=main_menu(msg.from_user.id))


@router.message(Command("files", "list"))
async def files_cmd(msg: Message) -> None:
    from .files import open_browser
    await open_browser(msg, msg.from_user.id, 0)


# ── explicit mirror / leech / clone commands ───────────────────────────────
@router.message(Command("mirror", "m"))
async def mirror_cmd(msg: Message, command: CommandObject) -> None:
    from .upload import start_task_for_url
    url = (command.args or "").strip()
    if not url:
        await msg.answer(t(f"{cards.emoji('upload')} <b>Usage:</b> "
                           f"<code>/mirror https://example.com/file.zip</code>\n"
                           f"{cards.emoji('info')} Or just send the link on its own."),
                         parse_mode="HTML")
        return
    await start_task_for_url(msg, url, mode="mirror")


@router.message(Command("leech", "l"))
async def leech_cmd(msg: Message, command: CommandObject) -> None:
    from .upload import start_task_for_url
    url = (command.args or "").strip()
    if not url:
        await msg.answer(t(f"{cards.emoji('download')} <b>Usage:</b> "
                           f"<code>/leech https://example.com/file.zip</code>"),
                         parse_mode="HTML")
        return
    await start_task_for_url(msg, url, mode="leech")


@router.message(Command("clone"))
async def clone_cmd(msg: Message, command: CommandObject) -> None:
    from .upload import start_task_for_url
    url = (command.args or "").strip()
    if not url:
        await msg.answer(t(f"{cards.emoji('cloud')} <b>Usage:</b> "
                           f"<code>/clone https://drive.google.com/file/d/FILE_ID/view</code>\n"
                           f"{cards.emoji('bolt')} Copies a Drive file into your Drive instantly "
                           f"(no download)."), parse_mode="HTML")
        return
    await start_task_for_url(msg, url, mode="mirror")

