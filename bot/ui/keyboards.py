"""Keyboard builders — premium icons + coloured (style) buttons where useful."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..config import settings
from .emoji import icon


def btn(text: str, data: str | None = None, *, url: str | None = None,
        emoji_key: str | None = None, style: str | None = None) -> InlineKeyboardButton:
    kw: dict = {"text": text}
    if url:
        kw["url"] = url
    else:
        kw["callback_data"] = data or "noop"
    if emoji_key and (cid := icon(emoji_key)):
        kw["icon_custom_emoji_id"] = cid
    if style:
        kw["style"] = style  # primary | success | danger (Bot API 9.0+)
    try:
        return InlineKeyboardButton(**kw)
    except TypeError:  # very old aiogram / API — drop the fancy fields
        kw.pop("style", None)
        kw.pop("icon_custom_emoji_id", None)
        return InlineKeyboardButton(**kw)


def ikb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


# ── main menu ──────────────────────────────────────────────────────────────
def main_menu(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [btn("Upload to Drive", "menu:upload", emoji_key="upload", style="success"),
         btn("Leech to Telegram", "menu:leech", emoji_key="download", style="primary")],
        [btn("Connect Google Drive", "menu:drive", emoji_key="login"),
         btn("Settings", "menu:settings", emoji_key="gear")],
        [btn("My Files", "menu:files", emoji_key="folder"),
         btn("Help", "menu:help", emoji_key="help")],
        [btn("Join Support", url=settings.support_group, emoji_key="heart"),
         btn("Channel", url=settings.update_channel, emoji_key="bell")],
    ]
    if user_id == settings.owner_id:
        rows.append([btn("Admin Panel", "menu:admin", emoji_key="crown", style="danger")])
    return ikb(*rows)


def back_menu(target: str = "menu:home") -> InlineKeyboardMarkup:
    return ikb([btn("Back", target, emoji_key="back")])


# ── upload mode ────────────────────────────────────────────────────────────
def upload_menu() -> InlineKeyboardMarkup:
    return ikb(
        [btn("Mirror → Google Drive", "mode:mirror", emoji_key="cloud", style="success"),
         btn("Leech → Telegram", "mode:leech", emoji_key="download", style="primary")],
        [btn("Back", "menu:home", emoji_key="back")],
    )


def confirm_leech(uid: str) -> InlineKeyboardMarkup:
    return ikb(
        [btn("Yes, leech it", f"leech:go:{uid}", emoji_key="check", style="success"),
         btn("Mirror to Drive instead", f"leech:drive:{uid}", emoji_key="cloud")],
        [btn("Cancel", f"leech:no:{uid}", emoji_key="cross", style="danger")],
    )


def cancel_row(uid: str) -> InlineKeyboardMarkup:
    return ikb([btn("Cancel task", f"task:cancel:{uid}", emoji_key="cross", style="danger")])


# ── drive / login ──────────────────────────────────────────────────────────
def drive_menu(connected: bool, can_sa: bool) -> InlineKeyboardMarkup:
    rows = []
    if connected:
        rows.append([btn("Disconnect Google", "drive:logout", emoji_key="logout", style="danger")])
        rows.append([btn("Test connection", "drive:test", emoji_key="bolt"),
                     btn("Change folder", "drive:folder", emoji_key="folder")])
    else:
        if settings.oauth_enabled:
            rows.append([btn("Login with Google (Email)", "drive:login", emoji_key="login", style="success")])
        if can_sa:
            rows.append([btn("Use bot's Service Account", "drive:sa", emoji_key="key")])
    rows.append([btn("Back", "menu:home", emoji_key="back")])
    return ikb(*rows)


def login_link(url: str) -> InlineKeyboardMarkup:
    return ikb(
        [btn("Open Google verification page", url=url, emoji_key="link", style="primary")],
        [btn("I've finished — verify", "drive:verifystart", emoji_key="check", style="success")],
        [btn("Cancel", "menu:drive", emoji_key="cross")],
    )


# ── settings ───────────────────────────────────────────────────────────────
def settings_menu(s: dict) -> InlineKeyboardMarkup:
    on = lambda b: "ON" if b else "OFF"  # noqa: E731
    return ikb(
        [btn(f"Upload as document: {on(s.get('as_doc', True))}", "set:as_doc", emoji_key="doc"),
         btn(f"Thumbnail: {on(s.get('thumb', True))}", "set:thumb", emoji_key="image")],
        [btn(f"Quality: {s.get('quality', 'best')}", "set:quality", emoji_key="video"),
         btn(f"Drive folder: {s.get('folder_name', 'My Drive')}", "set:folder", emoji_key="folder")],
        [btn(f"Auto-cleanup: {on(s.get('cleanup', True))}", "set:cleanup", emoji_key="trash")],
        [btn("Back", "menu:home", emoji_key="back")],
    )


def quality_menu(current: str) -> InlineKeyboardMarkup:
    choices = [("best", "Best available"), ("1080", "1080p"), ("720", "720p"),
               ("480", "480p"), ("audio", "Audio only (mp3)")]
    rows = [[btn(("✔ " if k == current else "") + label, f"set:quality:{k}", emoji_key="video")]
            for k, label in choices]
    rows.append([btn("Back", "menu:settings", emoji_key="back")])
    return ikb(*rows)


# ── files ──────────────────────────────────────────────────────────────────
def files_menu(row: dict | None, idx: int, total: int) -> InlineKeyboardMarkup:
    if not row:
        return ikb([btn("Back", "menu:home", emoji_key="back")])
    rows = [[btn("Download", f"file:dl:{row['id']}", emoji_key="download", style="primary"),
             btn("Copy link", f"file:link:{row['id']}", emoji_key="link")]]
    nav = []
    if idx > 0:
        nav.append(btn("Previous", f"file:page:{idx - 1}", emoji_key="back"))
    if idx < total - 1:
        nav.append(btn("Next", f"file:page:{idx + 1}", emoji_key="next"))
    if nav:
        rows.append(nav)
    rows.append([btn("Back", "menu:home", emoji_key="back")])
    return ikb(*rows)


# ── task actions ───────────────────────────────────────────────────────────
def task_done_menu(uid: str, web: str | None, cloud_file_id: str | None) -> InlineKeyboardMarkup:
    rows = []
    if web:
        rows.append([btn("Open in Google Drive", url=web, emoji_key="cloud", style="success")])
    if cloud_file_id:
        rows.append([btn("Show in My Files", "menu:files", emoji_key="folder")])
    rows.append([btn("New task", "menu:upload", emoji_key="rocket"),
                 btn("Home", "menu:home", emoji_key="home")])
    return ikb(*rows)


# ── admin ──────────────────────────────────────────────────────────────────
def admin_menu() -> InlineKeyboardMarkup:
    return ikb(
        [btn("Bot stats", "admin:stats", emoji_key="stats"),
         btn("Broadcast", "admin:cast", emoji_key="bell")],
        [btn("Emoji catalogue", "admin:emoji", emoji_key="star"),
         btn("Active tasks", "admin:tasks", emoji_key="list")],
        [btn("Activity log channel", "admin:logch", emoji_key="bell")],
        [btn("Back", "menu:home", emoji_key="back")],
    )


def cancel_action_row() -> InlineKeyboardMarkup:
    return ikb([btn("Cancel", "menu:home", emoji_key="cross")])
