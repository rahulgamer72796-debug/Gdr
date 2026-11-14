"""Drive browser — /files, pagination, download & copy-link buttons, folder picker."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from ..db import db
from ..drive import Drive, DriveError
from ..logger import log
from ..net import get_http
from ..services.downloads import gdrive_id
from ..services.tasks import manager
from ..ui import cards
from ..ui.emoji import t
from ..ui.keyboards import files_menu, main_menu
from ..utils import esc

router = Router(name="files")

AWAIT_FOLDER: set[int] = set()      # users who tapped "Change folder"
PAGE_CACHE: dict[int, dict] = {}    # user_id → {tokens: [...], rows: [...], folder: id}


async def try_folder_pick(msg: Message) -> bool:
    """If the user tapped 'Change folder', consume their next text as a folder id.

    Returns True when the message was consumed (so the caller stops routing).
    NOTE: deliberately *not* a router handler — a blanket text matcher placed
    before the upload router would swallow every link the user sends.
    """
    if msg.from_user.id not in AWAIT_FOLDER:
        return False
    text = (msg.text or "").strip()
    AWAIT_FOLDER.discard(msg.from_user.id)
    fid = gdrive_id(text) or (text if _looks_like_id(text) else "")
    if not fid:
        await msg.answer(t(f"{cards.emoji('cross')} That doesn't look like a folder id or link."),
                         parse_mode="HTML")
        return True
    user = await db.get_user(msg.from_user.id)
    if user["drive_mode"] not in ("oauth", "sa"):
        await msg.answer(t(f"{cards.emoji('login')} Connect Drive first with /login."),
                         parse_mode="HTML")
        return True
    try:
        drive = Drive(await get_http(), msg.from_user.id, user["drive_mode"])
        meta = await drive.get_meta(fid)
        if not (meta.get("mimeType") or "").endswith("folder"):
            await msg.answer(t(f"{cards.emoji('warn')} That's a file, not a folder — "
                               f"send a folder id/link."), parse_mode="HTML")
            return True
        await db.update_user(msg.from_user.id, folder_id=fid, folder_name=meta.get("name", fid)[:60])
        await msg.answer(t(f"{cards.emoji('check')} Upload folder set to "
                           f"<b>{esc(meta.get('name', fid))}</b>."),
                         parse_mode="HTML", reply_markup=main_menu(msg.from_user.id))
    except DriveError as e:
        await msg.answer(t(f"{cards.emoji('cross')} {e}"), parse_mode="HTML")
    return True


def _looks_like_id(text: str) -> bool:
    return bool(text) and len(text) >= 15 and " " not in text and "/" not in text


async def open_browser(msg: Message, user_id: int, idx: int = 0) -> None:
    user = await db.get_user(user_id)
    if user["drive_mode"] not in ("oauth", "sa"):
        await msg.answer(t(f"{cards.emoji('login')} <b>Connect Google Drive</b> to browse your files.\n"
                           f"{cards.emoji('info')} /login"), parse_mode="HTML",
                         reply_markup=main_menu(user_id))
        return
    try:
        drive = Drive(await get_http(), user_id, user["drive_mode"])
        body = await drive.list_files(folder_id=user["folder_id"], page_size=20)
    except DriveError as e:
        await msg.answer(t(f"{cards.emoji('cross')} {e}"), parse_mode="HTML")
        return
    rows = [f for f in (body.get("files") or []) if not (f.get("mimeType") or "").endswith("folder")]
    if not rows:
        await msg.answer(t(f"{cards.emoji('folder')} <b>Nothing here yet.</b>\n"
                           f"{cards.emoji('rocket')} Send me a link and your first file appears."),
                         parse_mode="HTML", reply_markup=main_menu(user_id))
        return
    PAGE_CACHE[user_id] = {"rows": rows}
    text = t(cards.file_card(rows[0], 0, len(rows)))
    await msg.answer(text, parse_mode="HTML", reply_markup=files_menu(rows[0], 0, len(rows)))


async def show_page(cb: CallbackQuery) -> None:
    cache = PAGE_CACHE.get(cb.from_user.id)
    if not cache:
        await open_browser(cb.message, cb.from_user.id)
        await cb.answer()
        return
    rows = cache["rows"]
    text = t(cards.file_card(rows[0], 0, len(rows)))
    try:
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=files_menu(rows[0], 0, len(rows)),
                                  )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            log.debug("files edit: %s", e)
    await cb.answer()


@router.callback_query(F.data.startswith("file:page:"))
async def page(cb: CallbackQuery) -> None:
    idx = int(cb.data.split(":")[2])
    cache = PAGE_CACHE.get(cb.from_user.id) or {}
    rows = cache.get("rows") or []
    if not (0 <= idx < len(rows)):
        await cb.answer("Nothing there.", show_alert=True)
        return
    row = rows[idx]
    try:
        await cb.message.edit_text(t(cards.file_card(row, idx, len(rows))), parse_mode="HTML",
                                   reply_markup=files_menu(row, idx, len(rows)),
                                  )
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("file:link:"))
async def copy_link(cb: CallbackQuery) -> None:
    fid = cb.data.split(":", 2)[2]
    link = f"https://drive.google.com/file/d/{fid}/view"
    await cb.answer(link, show_alert=True)


@router.callback_query(F.data.startswith("file:dl:"))
async def download_btn(cb: CallbackQuery) -> None:
    fid = cb.data.split(":", 2)[2]
    user = await db.get_user(cb.from_user.id)
    if user["drive_mode"] not in ("oauth", "sa"):
        await cb.answer("Connect Drive first.", show_alert=True)
        return
    await cb.answer("Downloading from your Drive…")
    url = f"https://drive.google.com/uc?export=download&id={fid}"
    task = await manager.submit(
        chat_id=cb.message.chat.id, user_id=cb.from_user.id, mode="leech", source=url,
        source_kind="url", quality=user["quality"], as_doc=bool(user["as_doc"]),
        thumb=bool(user["thumb"]))
    log.info("Drive→TG download task %s", task.id)
