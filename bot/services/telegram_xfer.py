"""Telegram ↔ bot file movement: leech upload + inline-bot download."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import aiohttp
from aiogram import Bot
from aiogram.types import FSInputFile

from ..utils import human_size

TG_API = "https://api.telegram.org/bot{token}/{method}"
# Bot API cloud limit for bots: 20 MB download from Telegram servers, 50 MB upload
# (2 GB with a self-hosted local Bot API server). We surface this clearly.
CLOUD_DOWNLOAD_LIMIT = 20 * 1024 * 1024
CLOUD_UPLOAD_LIMIT = 50 * 1024 * 1024
LOCAL_UPLOAD_LIMIT = 2000 * 1024 * 1024


class LeechError(Exception):
    pass


def effective_upload_limit(bot: Bot) -> int:
    """50 MB on the cloud Bot API, 2 GB when a self-hosted Bot API server is used.

    The session's `api` is a TelegramAPIServer whose `base` is the endpoint
    template, e.g. "http://localhost:8081/bot{token}/{method}".
    """
    try:
        api = getattr(bot.session, "api", None)
        base = str(getattr(api, "base", "")) if api else ""
        if base and "api.telegram.org" not in base:
            return LOCAL_UPLOAD_LIMIT
    except Exception:  # noqa: BLE001
        pass
    return CLOUD_UPLOAD_LIMIT


async def download_file_by_id(bot: Bot, file_id: str, dest: Path) -> Path:
    """getFile → stream to disk (used for Telegram-post sources)."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        tg_file = await bot.get_file(file_id)
    except Exception as e:  # noqa: BLE001
        raise LeechError(
            "Telegram won't let me fetch this file (above 20 MB needs a local "
            "Bot API server). Send it to my Drive mirror instead."
        ) from e
    if not tg_file.file_path:
        raise LeechError("Telegram returned no file path for this file.")
    url = f"https://api.telegram.org/file/bot{bot.token}/{tg_file.file_path}"
    out = dest / Path(tg_file.file_path).name
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            if r.status != 200:
                raise LeechError(f"Telegram file download failed ({r.status}).")
            with out.open("wb") as fh:
                async for chunk in r.content.iter_chunked(256 * 1024):
                    fh.write(chunk)
    return out


async def send_to_telegram(bot: Bot, chat_id: int, path: Path, *, caption: str,
                           as_document: bool = True, thumbnail: Optional[Path] = None,
                           effect: Optional[str] = None) -> None:
    """Leech: upload a file back to the user."""
    size = path.stat().st_size
    limit = effective_upload_limit(bot)
    if size > limit:
        raise LeechError(
            f"File is {human_size(size)} — over the {human_size(limit)} upload limit of the "
            f"Bot API. Use Mirror to Drive for this one (or self-host a local Bot API server)."
        )
    name = path.name.lower()
    kwargs = dict(chat_id=chat_id, caption=caption, parse_mode="HTML")
    if effect:
        kwargs["message_effect_id"] = effect
    file = FSInputFile(path)
    try:
        if not as_document and name.endswith((".mp4", ".mkv", ".webm", ".mov")):
            await bot.send_video(video=file, supports_streaming=True, **kwargs)
        elif not as_document and name.endswith((".mp3", ".m4a", ".flac", ".wav", ".opus")):
            await bot.send_audio(audio=file, **kwargs)
        elif not as_document and name.endswith((".jpg", ".jpeg", ".png", ".webp")):
            await bot.send_photo(photo=file, **kwargs)
        else:
            await bot.send_document(document=file,
                                    thumbnail=FSInputFile(thumbnail) if thumbnail and thumbnail.exists() else None,
                                    **kwargs)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "too big" in msg.lower() or "Request Entity Too Large" in msg:
            raise LeechError(
                f"Telegram refused the upload ({human_size(size)}). The cloud Bot API caps "
                f"bot uploads at 50 MB — mirror to Drive instead."
            ) from e
        raise


# ── inline-bot bridge (downloading a post/file from any chat) ───────────────
async def resolve_inline_message(bot: Bot, chat_ref: str, message_id: int) -> dict:
    """Fetch a public post's file via the `via_bot` trick? Not possible with
    plain Bot API — so we explain politely instead of pretending."""
    raise LeechError(
        "Telegram doesn't let an ordinary bot read other chats' posts. "
        "Forward the file/message to me directly (up to 20 MB), or send me its direct link."
    )


def jdump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)
