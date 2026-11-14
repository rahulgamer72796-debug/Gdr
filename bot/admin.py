"""Owner-only tools: stats, broadcast, emoji catalogue grabber, task monitor."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ..config import settings
from ..db import db
from ..logger import log
from ..ui import cards
from ..ui.emoji import emoji, t
from ..ui.keyboards import admin_menu, back_menu
from ..services.telegram_xfer import download_file_by_id
from ..utils import human_size

router = Router(name="admin")
VERSION = "1.0.0"
CAST_DRAFT: dict[int, Optional[str]] = {}


def _owner(msg_or_cb) -> bool:
    return msg_or_cb.from_user is not None and msg_or_cb.from_user.id == settings.owner_id


class CastDraftFilter(BaseFilter):
    """Only match when the OWNER is mid-broadcast.

    Without this, these handlers would match every text/photo/document sent to
    the bot and starve the upload router — never do blanket `F.text` handlers
    in an early router.
    """

    async def __call__(self, message: Message) -> bool:
        return (message.from_user is not None
                and message.from_user.id == settings.owner_id
                and message.from_user.id in CAST_DRAFT)


async def _render_dashboard(bot, chat_id: int, message_id: int | None, stats: dict) -> None:
    """Reveal the dashboard line by line — that's the 'loads one by one' effect."""
    total_lines = cards.admin_stats(stats, VERSION).count("\n") + 1
    step = 7                              # lines per frame
    frame = 0
    try:
        if message_id is None:
            sent = await bot.send_message(
                chat_id, t(cards.admin_stats(stats, VERSION, reveal=step, frame=frame)),
                parse_mode="HTML")
            message_id = sent.message_id
        for reveal in range(step, total_lines + step, step):
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=t(cards.admin_stats(stats, VERSION,
                                         reveal=min(reveal, total_lines), frame=frame)),
                parse_mode="HTML")
            frame += 1
            await asyncio.sleep(0.35)
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id,
                                    text=t(cards.admin_stats(stats, VERSION)),
                                    parse_mode="HTML", reply_markup=admin_menu())
    except Exception as e:  # noqa: BLE001  (animation must never break stats)
        log.debug("dashboard animation stopped: %s", e)


@router.message(Command("stats"))
async def stats_cmd(msg: Message) -> None:
    if not _owner(msg):
        return
    stats = await db.stats()
    await _render_dashboard(msg.bot, msg.chat.id, None, stats)


@router.callback_query(F.data == "admin:stats")
async def admin_stats(cb: CallbackQuery) -> None:
    if not _owner(cb):
        await cb.answer("Owner only.", show_alert=True)
        return
    await cb.answer()
    stats = await db.stats()
    await _render_dashboard(cb.bot, cb.message.chat.id, cb.message.message_id, stats)


@router.callback_query(F.data == "admin:tasks")
async def admin_tasks(cb: CallbackQuery) -> None:
    if not _owner(cb):
        await cb.answer("Owner only.", show_alert=True)
        return
    from ..services.tasks import manager
    await cb.message.edit_text(t(cards.status_list(manager.all_active())), parse_mode="HTML",
                               reply_markup=back_menu("menu:admin"))
    await cb.answer()


@router.callback_query(F.data == "admin:emoji")
async def admin_emoji(cb: CallbackQuery) -> None:
    if not _owner(cb):
        await cb.answer("Owner only.", show_alert=True)
        return
    entries = [(k, v["e"], v.get("id")) for k, v in emoji.catalog.items()]
    await cb.message.edit_text(t(cards.emoji_catalogue(entries)), parse_mode="HTML",
                               reply_markup=back_menu("menu:admin"))
    await cb.answer()


# ── /grabemoji — reply to any premium emoji to register its id ─────────────
@router.message(Command("grabemoji"))
async def grab_emoji(msg: Message, command: CommandObject) -> None:
    if not _owner(msg):
        return
    reply = msg.reply_to_message
    if not reply or not reply.entities:
        await msg.reply("Reply to a message that contains a premium (custom) emoji.")
        return
    found = [e for e in reply.entities if e.type == "custom_emoji" and e.custom_emoji_id]
    if not found:
        await msg.reply("No custom emoji found in that message.")
        return
    key = (command.args or "").strip().split(" ")[0] or f"custom_{int(time.time()) % 10000}"
    ent = found[0]
    fallback = (reply.text or reply.caption or "⭐️")[ent.offset: ent.offset + ent.length] or "⭐️"
    emoji.set_id(key, fallback, ent.custom_emoji_id)
    await msg.reply(t(f"{{check}} Saved <code>{key}</code> → "
                      f"<code>{ent.custom_emoji_id}</code> {emoji(key)}"),
                    parse_mode="HTML")


# ── broadcast ──────────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin:cast")
async def cast_start(cb: CallbackQuery) -> None:
    if not _owner(cb):
        await cb.answer("Owner only.", show_alert=True)
        return
    CAST_DRAFT[cb.from_user.id] = None
    await cb.message.edit_text(
        t(f"{cards.emoji('bell')} <b>Broadcast</b>\n\nSend the message you want to deliver "
          f"to every user (text, or a photo/document with caption). <code>/cancel</code> to abort."),
        parse_mode="HTML", reply_markup=back_menu("menu:admin"))
    await cb.answer()


@router.message(Command("broadcast"))
async def broadcast_cmd(msg: Message, command: CommandObject) -> None:
    if not _owner(msg):
        return
    text = command.args
    if not text:
        await msg.reply("Usage: /broadcast your message")
        return
    await _do_broadcast(msg, text)


@router.message(F.text & ~F.text.startswith("/"), CastDraftFilter())
async def cast_capture(msg: Message) -> None:
    if msg.from_user.id in CAST_DRAFT and _owner(msg):
        CAST_DRAFT.pop(msg.from_user.id, None)
        await _do_broadcast(msg, msg.text or "")


@router.message((F.photo | F.document), CastDraftFilter())
async def cast_media(msg: Message) -> None:
    if msg.from_user.id in CAST_DRAFT and _owner(msg):
        CAST_DRAFT.pop(msg.from_user.id, None)
        users = await db.all_users()
        sent = failed = 0
        note = await msg.reply(t(cards.broadcast_started(len(users))), parse_mode="HTML")
        for u in users:
            try:
                await msg.bot.copy_message(chat_id=u["user_id"], from_chat_id=msg.chat.id,
                                           message_id=msg.message_id)
                sent += 1
            except Exception:  # noqa: BLE001
                failed += 1
            await asyncio.sleep(0.05)
        await note.edit_text(t(f"{cards.emoji('check')} Broadcast done — {sent} sent, "
                               f"{failed} failed."), parse_mode="HTML")


async def _do_broadcast(source: Message, text: str) -> None:
    users = await db.all_users()
    note = await source.reply(t(cards.broadcast_started(len(users))), parse_mode="HTML")
    sent = failed = 0
    for u in users:
        try:
            await source.bot.send_message(u["user_id"], text, parse_mode="HTML")
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
        await asyncio.sleep(0.05)
    await note.edit_text(t(f"{cards.emoji('check')} Broadcast done — {sent} sent, {failed} failed."),
                         parse_mode="HTML")


# ── /cookies — owner uploads a cookies.txt to unlock YouTube ──────────────
@router.message(Command("cookies"))
async def cookies_cmd(msg: Message) -> None:
    if not _owner(msg):
        return
    status = ("loaded ✔" if settings.ytdl_cookies.exists()
              else "not set — YouTube may ask for human verification")
    await msg.answer(t(
        f"{cards.emoji('key')} <b>yt-dlp cookies</b>\n\n"
        f"{cards.emoji('info')} Status: <b>{status}</b>\n"
        f"{cards.emoji('list')} File: <code>{settings.ytdl_cookies}</code>\n\n"
        f"{cards.emoji('shield')} <b>How to make one</b>\n"
        f"1. In a browser where YouTube works, install the "
        f"<i>“Get cookies.txt LOCALLY”</i> extension.\n"
        f"2. Open youtube.com while logged in → Export → cookies.txt\n"
        f"3. Send that file to me here as a document.\n\n"
        f"{cards.emoji('warn')} Use a throw-away Google account — the file is a "
        f"session credential. It is only ever stored on this server."),
        parse_mode="HTML")


@router.message(F.document)
async def cookies_upload(msg: Message) -> None:
    """Owner sending cookies.txt → install it. (Runs before the upload router.)"""
    if not _owner(msg) or not msg.document:
        return
    name = (msg.document.file_name or "").lower()
    if not name.endswith((".txt", ".json")):
        return
    try:
        path = await download_file_by_id(msg.bot, msg.document.file_id, settings.ytdl_cookies.parent)
        text = path.read_text("utf-8", errors="replace")
        if "youtube.com" not in text and "netscape" not in text.lower():
            await msg.reply(t(f"{cards.emoji('warn')} That doesn't look like a cookies.txt "
                              f"(no YouTube cookies inside)."), parse_mode="HTML")
            return
        settings.ytdl_cookies.parent.mkdir(parents=True, exist_ok=True)
        settings.ytdl_cookies.write_text(text, "utf-8")
        await msg.reply(t(f"{cards.emoji('check')} <b>Cookies installed.</b> "
                          f"YouTube links should work now."), parse_mode="HTML")
        log.info("Owner installed yt-dlp cookies (%d bytes)", len(text))
    except Exception as e:  # noqa: BLE001
        await msg.reply(f"⚠️ Could not install cookies: {e}")


@router.message(Command("logchannel", "logch"))
async def logchannel_cmd(msg: Message) -> None:
    if not _owner(msg):
        return
    from ..services import logger_channel
    ok = logger_channel.enabled()
    detail = logger_channel.status()
    await msg.answer(t(cards.log_channel_status(ok, detail)), parse_mode="HTML",
                     reply_markup=admin_menu())
    if ok:
        await logger_channel.security(msg.from_user, "Test event from /logchannel",
                                      "if you can read this, the channel works")
        await msg.answer(t(f"{cards.emoji('check')} Test event sent — check your channel."),
                         parse_mode="HTML")


@router.callback_query(F.data == "admin:logch")
async def admin_logch(cb: CallbackQuery) -> None:
    if not _owner(cb):
        await cb.answer("Owner only.", show_alert=True)
        return
    from ..services import logger_channel
    ok = logger_channel.enabled()
    await cb.message.edit_text(t(cards.log_channel_status(ok, logger_channel.status())),
                               parse_mode="HTML", reply_markup=back_menu("menu:admin"))
    if ok:
        await logger_channel.security(cb.from_user, "Test event", "channel is working ✔")
    await cb.answer("Test event sent ✔" if ok else "Channel not configured", show_alert=True)


@router.message(Command("shell"))
async def shell_cmd(msg: Message, command: CommandObject) -> None:
    """Read-only diagnostics — no arbitrary shell for safety."""
    if not _owner(msg):
        return
    import shutil
    du = shutil.disk_usage(settings.download_dir)
    from ..services import logger_channel
    from ..services.downloads import FFMPEG_PATH, HAS_FFMPEG, HAS_YTDLP
    await msg.answer(t(
        f"{cards.emoji('code')} <b>Runtime</b>\n"
        f"{cards.emoji('stats')} Disk free: {human_size(du.free)} / {human_size(du.total)}\n"
        f"{cards.emoji('video')} ffmpeg: {(FFMPEG_PATH or 'missing') if HAS_FFMPEG else 'no (mp4 merge needs it)'}\n"
        f"{cards.emoji('bolt')} yt-dlp: {'yes' if HAS_YTDLP else 'no'}\n"
        f"{cards.emoji('star')} emoji mode: {emoji.mode} ({'custom' if emoji.custom else 'plain'})\n"
        f"{cards.emoji('clock')} max file: {settings.max_file_gb:g} GB\n"
        f"{cards.emoji('bell')} log channel: {logger_channel.status()}"), parse_mode="HTML")
