"""Task engine — queue, run, animate, finish.

One `Task` = one download→destination pipeline. While it runs, a background
"animator" edits a single status message every few seconds, which is what makes
the bot feel alive: rotating spinner, pulsing bar, changing status lines, ETA.
"""
from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from ..config import settings
from ..db import db
from ..drive import (AuthExpired, Drive, DriveError, UploadCancelled, copy_tree,
                     upload_tree)
from ..logger import log
from ..net import get_http
from . import logger_channel
from ..ui import cards
from ..ui.cards import t
from ..utils import clip, esc, human_size
from .common import CancelledTask, Progress
from .downloads import DownloadError, download, gdrive_id, is_gdrive
from .telegram_xfer import LeechError, download_file_by_id, send_to_telegram

EFFECT_CONFETTI = "5046509860389126442"
EFFECT_FIRE = "5104841245755180586"


@dataclass
class Task:
    id: str
    user_id: int
    chat_id: int
    mode: str                          # mirror | leech | clone
    source: str                        # url / file_id / local path
    source_kind: str = "url"           # url | tg_file | tg_link | magnet
    caption: str = ""
    progress: Progress = field(default_factory=Progress)
    name: str = ""
    size: int = 0
    card_id: Optional[int] = None
    frame: int = 0
    finished: bool = False
    result_link: str = ""
    cloud_id: str = ""
    folder_id: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    quality: str = "best"
    as_doc: bool = True
    thumb: bool = True

    @property
    def display_source(self) -> str:
        if self.source_kind == "tg_file":
            return self.name or "Telegram file"
        return clip(self.source, 70)

    @property
    def elapsed(self) -> float:
        end = self.ended_at or time.time()
        return max(0.0, end - (self.started_at or end))


def _ensure_disk_space(task: Task) -> None:
    """Fail fast (with a useful message) instead of filling the disk mid-upload."""
    if not task.size:
        return
    try:
        free = shutil.disk_usage(settings.download_dir).free
    except OSError:
        return
    needed = task.size * 1.02          # tiny headroom
    if needed > free:
        raise DownloadError(
            f"This file is {human_size(task.size)} but only {human_size(free)} of disk is "
            f"free. Free some space (or mount a bigger volume at DOWNLOAD_DIR) and retry.")


class TaskManager:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self._sem: Optional[asyncio.Semaphore] = None
        self._workers: set[asyncio.Task] = set()
        self.bot: Optional[Bot] = None

    def setup(self, bot: Bot) -> None:
        self.bot = bot
        self._sem = asyncio.Semaphore(settings.max_concurrent)

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def submit(self, *, chat_id: int, user_id: int, mode: str, source: str,
                     source_kind: str = "url", name: str = "", size: int = 0,
                     folder_id: str = "", quality: str = "best",
                     as_doc: bool = True, thumb: bool = True) -> Task:
        assert self.bot and self._sem
        tid = await db.new_task(user_id, mode, source if source_kind == "url" else name)
        task = Task(
            id=tid, user_id=user_id, chat_id=chat_id, mode=mode, source=source,
            source_kind=source_kind, name=name, size=size, folder_id=folder_id,
            quality=quality, as_doc=as_doc, thumb=thumb,
        )
        task.progress.update(name=name or "", total=size or 0, phase="queued")
        self.tasks[tid] = task

        card = await self.bot.send_message(chat_id, t(cards.queued(task)), parse_mode="HTML")
        task.card_id = card.message_id

        worker = asyncio.create_task(self._runner(task))
        self._workers.add(worker)
        worker.add_done_callback(self._workers.discard)
        return task

    async def cancel(self, task_id: str, by_user: bool = False) -> bool:
        task = self.tasks.get(task_id)
        if not task or task.finished:
            return False
        task.progress.cancel()
        if by_user:
            task.progress.update(note="Cancelling…")
        return True

    def active_for_user(self, user_id: int) -> list[Task]:
        return [t_ for t_ in self.tasks.values() if t_.user_id == user_id and not t_.finished]

    def all_active(self) -> list[Task]:
        return [t_ for t_ in self.tasks.values() if not t_.finished]

    # ── runner ─────────────────────────────────────────────────────────────
    async def _runner(self, task: Task) -> None:
        assert self._sem
        animator = asyncio.create_task(self._animate(task))
        workdir = settings.download_dir / task.id
        status, error = "failed", ""
        try:
            async with self._sem:                    # wait for a free slot
                log.info("▶ task %s (%s) started → %s", task.id, task.mode, task.source[:80])
                try:
                    await logger_channel.task_started(None, task)
                except Exception:  # noqa: BLE001
                    pass
                task.started_at = time.time()
                task.progress.update(phase="starting")
                await db.update_task(task.id, status="running")
                await self._pipeline(task, workdir)
            status = "done"
            log.info("✔ task %s done in %.1fs", task.id, time.time() - task.started_at)
        except (CancelledTask, UploadCancelled):
            status, error = "cancelled", ""
        except AuthExpired as e:
            error = f"{e} — reconnect with /login."
        except (DriveError, DownloadError, LeechError) as e:
            error = str(e)
            log.warning("✖ task %s failed: %s", task.id, error)
        except Exception as e:  # noqa: BLE001
            log.exception("Task %s crashed", task.id)
            error = f"Unexpected error: {e}"
        finally:
            task.ended_at = time.time()
            task.finished = True
            task.progress.update(phase="done" if status == "done" else status)
            await asyncio.sleep(0)                    # let animator exit
            animator.cancel()
            try:
                await animator
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await self._final_card(task, status, error)
            if status == "done":
                self._maybe_effect(task)
            await db.update_task(task.id, name=task.name, size=task.size,
                                 dest=task.result_link, cloud_id=task.cloud_id)
            await db.finish_task(task.id, status, error)
            try:
                await logger_channel.task_finished(None, task, status, error)
            except Exception:  # noqa: BLE001
                pass
            if status == "done":
                await db.add_bytes(task.size)
            # respect the per-user "auto-cleanup" switch (falls back to global)
            cleanup = True
            try:
                cleanup = bool((await db.get_user(task.user_id))["cleanup"])
            except Exception:  # noqa: BLE001
                cleanup = settings.auto_cleanup
            if cleanup or settings.auto_cleanup:
                shutil.rmtree(workdir, ignore_errors=True)
            self.tasks.pop(task.id, None)

    async def _pipeline(self, task: Task, workdir: Path) -> None:
        assert self.bot
        workdir.mkdir(parents=True, exist_ok=True)
        user = await db.get_user(task.user_id)
        _ensure_disk_space(task)

        # ── 1. Google Drive source → server-side clone (no download!) ──────
        if task.source_kind == "url" and is_gdrive(task.source):
            fid = gdrive_id(task.source)
            if task.mode == "mirror" and user["drive_mode"] in ("oauth", "sa"):
                drive = Drive(await get_http(), task.user_id, user["drive_mode"])
                dest_folder = task.folder_id or user["folder_id"]
                is_folder = await drive.is_folder(fid)
                task.progress.update(phase="cloning",
                                     name=("Drive folder" if is_folder else "Drive file")
                                          + f" {fid[:10]}…")
                if is_folder:
                    async def _clone_report(name: str, done: int, total: int) -> None:
                        task.progress.update(note=f"cloning {name}", done=done, total=total)
                    stats = await copy_tree(drive, fid, dest_folder, report=_clone_report)
                    task.cloud_id = stats["root"]
                    task.result_link = f"https://drive.google.com/drive/folders/{stats['root']}"
                    task.name = f"Folder clone ({stats['files']} files)"
                    task.size = task.size or 1
                else:
                    meta = await drive.copy(fid, dest_folder)
                    task.cloud_id = meta.get("id", "")
                    task.result_link = meta.get("webViewLink", "")
                    task.name = meta.get("name", task.name) or task.name
                    task.size = task.size or int(meta.get("size") or 0)
                return
            # not connected → fall through and download it publicly

        # ── 2. Get the bytes onto disk ─────────────────────────────────────
        files: list[Path] = []
        if task.source_kind == "tg_file":
            task.progress.update(phase="downloading", name=task.name)
            path = await download_file_by_id(self.bot, task.source, workdir)
            task.progress.update(done=path.stat().st_size, total=path.stat().st_size)
            files = [path]
        elif task.source_kind == "tg_link":
            raise DownloadError(
                "Reading messages from other chats isn't allowed for ordinary bots. "
                "Forward the file to me, or give me a direct link.")
        elif task.source_kind == "magnet":
            raise DownloadError(
                "Torrents need aria2c/qBittorrent which this deployment doesn't run. "
                "Paste a *direct* download link instead.")
        else:
            url = task.source
            if is_gdrive(url) and task.mode != "mirror":
                url = f"https://drive.google.com/uc?export=download&id={gdrive_id(url)}"
            task.progress.update(phase="downloading")
            files = await download(await get_http(), url, workdir, task.progress,
                                   quality=task.quality)

        if not files:
            raise DownloadError("Nothing was downloaded.")
        task.size = sum(f.stat().st_size for f in files)
        if not task.name:
            task.name = files[0].name if len(files) == 1 else f"{files[0].parent.name}/"
        task.progress.update(name=task.name, total=task.size, done=task.size)

        # ── 3. Deliver ─────────────────────────────────────────────────────
        if task.mode == "leech":
            task.progress.update(phase="leeching")
            if len(files) == 1:
                cap = t(f"{cards.emoji('check')} <b>{esc(clip(task.name, 60))}</b>\n"
                        f"{cards.emoji('stats')} {human_size(task.size)} · MirrorX")
                await send_to_telegram(self.bot, task.chat_id, files[0], caption=cap,
                                       as_document=task.as_doc, thumbnail=None,
                                       effect=EFFECT_CONFETTI if settings.message_effects else None)
            else:
                for i, f in enumerate(files[:10], 1):
                    cap = t(f"{cards.emoji('check')} <b>{esc(clip(f.name, 55))}</b>\n"
                            f"{cards.emoji('list')} {i}/{len(files)} · {human_size(f.stat().st_size)}")
                    await send_to_telegram(self.bot, task.chat_id, f, caption=cap,
                                           as_document=True)
            task.result_link = "telegram"
            return

        # mirror → Drive
        if user["drive_mode"] not in ("oauth", "sa"):
            raise AuthExpired("No Google account connected — tap /login first.")
        drive = Drive(await get_http(), task.user_id, user["drive_mode"])
        dest = task.folder_id or user["folder_id"]

        multi = len(files) > 1

        async def on_progress(done: float, total: float) -> None:
            task.progress.update(done=int(done), total=int(total), phase="uploading")

        async def on_report(fname: str, _d: int, _tot: int) -> None:
            if multi:
                task.progress.update(name=fname, note=f"uploading {fname}")

        task.progress.update(phase="uploading", done=0, total=task.size)
        metas = await upload_tree(drive, files[0] if len(files) == 1 else workdir,
                                 dest, progress=on_progress, report=on_report,
                                 should_cancel=lambda: task.progress.cancelled)
        if metas:
            task.cloud_id = metas[0].get("id", "")
            task.result_link = metas[0].get("webViewLink", "") or f"https://drive.google.com/file/d/{task.cloud_id}/view"
            if len(metas) > 1:
                task.result_link = f"https://drive.google.com/drive/folders/{dest}" if dest else task.result_link

    # ── animation ──────────────────────────────────────────────────────────
    async def _animate(self, task: Task) -> None:
        assert self.bot
        interval = settings.progress_interval
        try:
            while not task.finished:
                # render first, *then* wait → the user sees movement instantly
                if task.card_id:
                    text = cards.running(task) if task.started_at else t(cards.queued(task))
                    task.frame += 1
                    try:
                        await self.bot.edit_message_text(
                            chat_id=task.chat_id, message_id=task.card_id,
                            text=text, parse_mode="HTML",
                           )
                    except TelegramRetryAfter as e:
                        interval = max(interval, e.retry_after + 1)
                    except TelegramBadRequest as e:
                        if "message is not modified" not in str(e).lower():
                            log.debug("Edit failed: %s", e)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.debug("Animator stopped: %s", e)

    # ── final card ─────────────────────────────────────────────────────────
    async def _final_card(self, task: Task, status: str, error: str) -> None:
        assert self.bot
        if status == "done":
            text = t(cards.done(task, task.result_link if task.result_link.startswith("http") else ""))
        elif status == "cancelled":
            text = t(cards.cancelled(task))
        else:
            text = t(cards.failed(task, error or "unknown error"))
        if task.card_id:
            try:
                await self.bot.edit_message_text(chat_id=task.chat_id, message_id=task.card_id,
                                                 text=text, parse_mode="HTML",
                                                )
            except Exception as e:  # noqa: BLE001
                log.debug("Final edit failed (%s) — sending fresh card", e)
                try:
                    await self.bot.send_message(task.chat_id, text, parse_mode="HTML")
                except Exception:  # noqa: BLE001
                    pass
        else:
            await self.bot.send_message(task.chat_id, text, parse_mode="HTML")

    def _maybe_effect(self, task: Task) -> None:
        """Fire a little celebration bubble (client-side animation)."""
        if not settings.message_effects or not self.bot:
            return

        async def _fire() -> None:
            try:
                await self.bot.send_message(
                    task.chat_id, t("{party} <b>Cloned!</b> {rocket}"),
                    parse_mode="HTML", message_effect_id=EFFECT_CONFETTI)
            except Exception:  # noqa: BLE001
                pass

        asyncio.create_task(_fire())


manager = TaskManager()
