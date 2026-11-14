"""Intake — every way content gets into the bot: links, files, videos, media groups."""
from __future__ import annotations

from typing import Optional

from aiogram import Bot, F, Router
from aiogram.types import Message

from ..db import db
from ..logger import log
from ..services.downloads import is_gdrive, is_media_site
from ..services.tasks import manager
from ..ui import cards
from ..ui.emoji import t
from ..ui.keyboards import cancel_row, main_menu
from ..utils import human_size, parse_tg_link, safe_url

router = Router(name="upload")
PENDING: dict[int, dict] = {}      # user_id → last big-file confirmation


async def _user_cfg(user_id: int) -> dict:
    return await db.get_user(user_id)


def _is_url(text: str) -> bool:
    t_ = (text or "").strip()
    if t_.startswith(("http://", "https://", "www.")):
        return True
    return "." in t_ and "/" in t_ and " " not in t_ and not t_.startswith("@")


async def start_task_for_url(msg: Message, url: str, mode: Optional[str] = None) -> None:
    user = await _user_cfg(msg.from_user.id)
    if mode is None:  # no explicit command → follow the default: mirror
        mode = "mirror"
    if user["drive_mode"] == "none" and mode == "mirror":
        await msg.answer(
            t(f"{cards.emoji('login')} <b>Google Drive isn't connected yet.</b>\n\n"
              f"{cards.emoji('info')} Tap the button — it takes about 20 seconds, "
              f"then send the link again."),
            parse_mode="HTML",
            reply_markup=main_menu(msg.from_user.id))
        return

    if url.lower().startswith("magnet:") or url.lower().endswith(".torrent"):
        await msg.answer(
            t(f"{cards.emoji('warn')} <b>Torrents aren't enabled in this build.</b>\n\n"
              f"{cards.emoji('info')} MirrorX v1 handles direct links, media sites, Drive "
              f"links and Telegram files. Torrent support needs an aria2c/qBittorrent daemon "
              f"next to the bot — say the word and I'll add it."),
            parse_mode="HTML")
        return
    clean = safe_url(url)
    if not clean:
        await msg.answer(
            t(f"{cards.emoji('cross')} <b>That doesn't look like a valid link.</b>\n\n"
              f"{cards.emoji('info')} Send a full URL, e.g. "
              f"<code>https://example.com/file.zip</code>"), parse_mode="HTML")
        return
    url = clean
    kind = "url"
    if parse_tg_link(url) and "t.me" in url:
        kind = "tg_link"
    if url.lower().startswith("magnet:"):
        kind = "magnet"

    hint = ""
    if is_gdrive(url) and mode == "mirror" and user["drive_mode"] in ("oauth", "sa"):
        hint = " · server-side clone (no download)"
    elif is_media_site(url):
        hint = " · media site detected"

    task = await manager.submit(
        chat_id=msg.chat.id, user_id=msg.from_user.id, mode=mode, source=url,
        source_kind=kind, quality=user["quality"], folder_id=user["folder_id"],
        as_doc=bool(user["as_doc"]), thumb=bool(user["thumb"]),
    )
    if hint:
        await msg.answer(t(f"{cards.emoji('bolt')} Task <b>#{task.id[:6]}</b>{hint}"),
                         parse_mode="HTML", reply_markup=cancel_row(task.id))


async def _handle_file(msg: Message, bot: Bot) -> None:
    user = await _user_cfg(msg.from_user.id)
    obj = msg.document or msg.video or msg.audio or (msg.video_note) or \
          (msg.photo[-1] if msg.photo else None) or msg.animation
    if obj is None:
        return
    file_id = obj.file_id
    name = getattr(obj, "file_name", None) or (
        f"photo_{msg.message_id}.jpg" if msg.photo else
        f"video_{msg.message_id}.mp4" if (msg.video or msg.video_note) else
        f"audio_{msg.message_id}.mp3" if msg.audio else
        f"file_{msg.message_id}.bin")
    size = getattr(obj, "file_size", 0) or 0
    caption = (msg.caption or "").strip()

    # caption can carry an explicit mode: "leech" or "mirror"
    mode = "mirror"
    if caption.lower().startswith("leech"):
        mode = "leech"

    if mode == "mirror" and user["drive_mode"] == "none":
        await msg.answer(
            t(f"{cards.emoji('login')} <b>Connect Google Drive first.</b>\n"
              f"{cards.emoji('info')} /login — then send the file again.\n"
              f"{cards.emoji('download')} Or reply <b>leech</b> in the caption to get it back here."),
            parse_mode="HTML", reply_markup=main_menu(msg.from_user.id))
        return

    if mode == "leech" and size > 50 * 1024 * 1024:
        await msg.answer(
            t(f"{cards.emoji('warn')} <b>This file is {human_size(size)}.</b>\n\n"
              f"Telegram's cloud Bot API refuses bot uploads over 50 MB. "
              f"I can mirror it to <b>Google Drive</b> instead — or you can self-host a "
              f"local Bot API server to unlock 2 GB leech."),
            parse_mode="HTML")

    task = await manager.submit(
        chat_id=msg.chat.id, user_id=msg.from_user.id, mode=mode, source=file_id,
        source_kind="tg_file", name=name, size=size, quality=user["quality"],
        folder_id=user["folder_id"], as_doc=bool(user["as_doc"]), thumb=bool(user["thumb"]),
    )
    log.info("TG file task %s (%s, %s)", task.id, name, human_size(size))


# ── message handlers ───────────────────────────────────────────────────────
@router.message(F.document | F.video | F.audio | F.video_note | F.animation | F.photo)
async def on_file(msg: Message, bot: Bot) -> None:
    await _handle_file(msg, bot)


@router.message(F.text.regexp(r"^((https?://|www\.)\S+|magnet:\?\S+)$"))
async def on_url(msg: Message) -> None:
    await start_task_for_url(msg, msg.text.strip(), mode=None)


@router.message(F.text)
async def on_text(msg: Message, bot: Bot) -> None:
    text = (msg.text or "").strip()
    if text.startswith("/"):
        return
    from .files import try_folder_pick
    if await try_folder_pick(msg):
        return
    if _is_url(text):
        await start_task_for_url(msg, text, mode=None)
        return
    # plain text → gentle guidance, never silence
    await msg.answer(
        t(f"{cards.emoji('info')} Send me a <b>link</b>, a <b>file</b>, or use the menu — "
          f"I turn it into a Google Drive upload.\n\n"
          f"{cards.emoji('help')} /help shows everything I can do."),
        parse_mode="HTML", reply_markup=main_menu(msg.from_user.id))
