"""Log / activity channel — the "lock channel".

Every meaningful event is pushed to ONE private Telegram channel that only you
(the owner) and your admins can read. Think of it as an audit trail:

    🔔 New user       →  who joined, their id, username, language
    🚀 Task started   →  mode, source, size, quality
    ✅ Task finished  →  size, duration, Drive link / Telegram
    ❌ Task failed    →  the exact reason
    🛑 Cancelled      →  how far it got
    🔐 Drive login    →  which Google account got connected
    👑 Admin action   →  broadcast, cookies installed, emoji added

Design rules:
  • **Never breaks the bot.** Every send is wrapped; a missing channel or a
    revoked bot just logs a warning once and the bot keeps working.
  • **Never leaks secrets.** Tokens, cookies and keys are never included.
  • **Never spams.** Per-user rate limit (default 3 events / 10 s) so one user
    hammering /start can't flood your channel; failures are always let through.
  • **No-op when disabled** — with LOG_CHANNEL_ID=0 nothing happens at all.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from ..config import settings
from ..logger import log
from ..ui.emoji import emoji, t
from ..utils import clip, esc, human_size, human_time

# ── internal state ─────────────────────────────────────────────────────────
_bot: Optional[Bot] = None
_disabled_reason: str = ""
_rate: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
RATE_LIMIT = 3          # events per user …
RATE_WINDOW = 10.0      # … per this many seconds


def setup(bot: Bot) -> None:
    """Called once at startup."""
    global _bot
    _bot = bot


def enabled() -> bool:
    return bool(settings.log_channel_id and _bot and not _disabled_reason)


def status() -> str:
    if not settings.log_channel_id:
        return "disabled (LOG_CHANNEL_ID not set)"
    if _disabled_reason:
        return f"error: {_disabled_reason}"
    return f"active → {settings.log_channel_id}"


def _throttled(user_id: int) -> bool:
    now = time.time()
    q = _rate[user_id]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


async def _send(text: str, *, user_id: int = 0, urgent: bool = False) -> None:
    """Fire-and-forget send with graceful degradation."""
    global _disabled_reason
    if not enabled():
        return
    if user_id and not urgent and _throttled(user_id):
        log.debug("log-channel: throttled event for user %s", user_id)
        return
    try:
        await _bot.send_message(settings.log_channel_id, text, parse_mode="HTML",
                                disable_notification=not urgent
                                if hasattr(_bot.send_message, "disable_notification")
                                else False)
    except TelegramRetryAfter as e:
        await asyncio.sleep(min(e.retry_after, 30))
        try:
            await _bot.send_message(settings.log_channel_id, text, parse_mode="HTML")
        except TelegramAPIError as e2:
            _fail(e2)
    except TelegramAPIError as e:
        _fail(e)


def _fail(err: Exception) -> None:
    """First failure explains itself; after that we stay quiet."""
    global _disabled_reason
    msg = str(err)
    if "chat not found" in msg.lower() or "bot was kicked" in msg.lower():
        _disabled_reason = ("bot is not an admin in LOG_CHANNEL_ID / channel missing")
    elif "not enough rights" in msg.lower():
        _disabled_reason = "bot needs 'Post Messages' permission in the channel"
    else:
        _disabled_reason = clip(msg, 90)
    log.warning("Log channel disabled: %s", _disabled_reason)


def _who(user) -> str:
    if user is None:
        return "unknown"
    name = esc(user.first_name or "user")
    handle = f"@{user.username}" if getattr(user, "username", None) else "no-username"
    return f"{name} · <code>{user.id}</code> · {handle}"


def _when() -> str:
    return time.strftime("%d %b %Y · %H:%M:%S")


# ══════════════════════════════════════════════════════════════════════════
#  Public events
# ══════════════════════════════════════════════════════════════════════════
async def new_user(user, *, is_new: bool = False) -> None:
    if not settings.log_new_users or not is_new:
        return
    await _send(
        t(f"{emoji('user')} <b>New user</b>\n\n"
          f"{emoji('info')} {_who(user)}\n"
          f"{emoji('clock')} {_when()}"),
        user_id=user.id)


async def command(user, text: str) -> None:
    """Lightweight pulse of what people run (throttled hard)."""
    await _send(
        t(f"{emoji('code')} <b>Command</b>  <code>{esc(clip(text, 40))}</code>\n"
          f"{emoji('user')} {_who(user)}"),
        user_id=user.id)


async def task_started(user, task) -> None:
    if not settings.log_tasks:
        return
    src = task.source if task.source_kind == "url" else (task.name or "telegram file")
    await _send(
        t(f"{emoji('rocket')} <b>Task started</b>  <code>#{task.id[:6]}</code>\n\n"
          f"{emoji('user')} {_who(user)}\n"
          f"{emoji('upload' if task.mode == 'mirror' else 'download')} Mode: <b>{task.mode}</b>\n"
          f"{emoji('link')} <code>{esc(clip(src, 70))}</code>\n"
          f"{emoji('info')} Size: {human_size(task.size) if task.size else 'unknown'}"
          + (f" · quality {task.quality}" if task.quality else "")),
        user_id=user.id if user else task.user_id)


async def task_finished(user, task, status: str, error: str = "") -> None:
    if not settings.log_tasks:
        return
    uid = user.id if user else task.user_id
    head = {
        "done": f"{emoji('check')} <b>Task finished</b>",
        "failed": f"{emoji('cross')} <b>Task failed</b>",
        "cancelled": f"{emoji('cross')} <b>Task cancelled</b>",
    }.get(status, f"{emoji('info')} <b>Task {status}</b>")
    body = (f"{head}  <code>#{task.id[:6]}</code>\n\n"
            f"{emoji('user')} {_who(user)}\n"
            f"{emoji('doc')} <code>{esc(clip(task.name or task.display_source, 55))}</code>\n"
            f"{emoji('stats')} {human_size(task.size)} · {human_time(task.elapsed)}")
    if status == "done" and task.result_link.startswith("http"):
        body += f"\n{emoji('link')} <a href=\"{esc(task.result_link)}\">open</a>"
    if error:
        body += f"\n{emoji('warn')} <i>{esc(clip(error, 180))}</i>"
    await _send(t(body), user_id=uid, urgent=status != "done")


async def drive_linked(user, email: str, mode: str) -> None:
    await _send(
        t(f"{emoji('login')} <b>Google Drive connected</b>\n\n"
          f"{emoji('user')} {_who(user)}\n"
          f"{emoji('key')} <code>{esc(email)}</code>\n"
          f"{emoji('shield')} mode: {mode}"),
        user_id=user.id if user else 0, urgent=True)


async def admin_action(actor, action: str, detail: str = "") -> None:
    if not settings.log_admins:
        return
    await _send(
        t(f"{emoji('crown')} <b>Admin action</b>\n\n"
          f"{emoji('user')} {_who(actor)}\n"
          f"{emoji('gear')} <b>{esc(action)}</b>"
          + (f"\n{emoji('info')} {esc(clip(detail, 160))}" if detail else "")),
        user_id=actor.id if actor else 0, urgent=True)


async def security(user, event: str, detail: str = "") -> None:
    await _send(
        t(f"{emoji('shield')} <b>{esc(event)}</b>\n\n"
          f"{emoji('user')} {_who(user)}\n"
          + (f"{emoji('warn')} {esc(clip(detail, 160))}" if detail else "")),
        user_id=user.id if user else 0, urgent=True)


async def startup(version: str) -> None:
    """One green message when the bot comes online — proves the channel works."""
    await _send(
        t(f"{emoji('rocket')} <b>{settings.bot_name} is online</b>\n\n"
          f"{emoji('info')} version {version}\n"
          f"{emoji('clock')} {_when()}\n"
          f"{emoji('shield')} acting as activity log"),
        urgent=True)
