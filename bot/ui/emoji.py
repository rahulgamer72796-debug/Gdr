"""Premium (animated) emoji engine.

Telegram renders `<tg-emoji emoji-id="…">🔥</tg-emoji>` as a *custom premium
emoji* when the bot's owner has Telegram Premium (Bot API 9.4+), or when the
bot owns a Fragment username. Every emoji therefore has a plain-unicode
fallback, and the engine degrades gracefully (one failed send → whole bot
switches to plain emojis, no user-facing errors).

The catalogue lives in `data/custom_emojis.json` and can be extended live from
Telegram with `/grabemoji` (reply to any premium emoji) — see handlers/admin.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..config import ROOT, settings
from ..logger import log

CATALOG_FILE: Path = ROOT / "data" / "custom_emojis.json"

# key → (fallback unicode, custom_emoji_id | None)
DEFAULT_CATALOG: dict[str, dict] = {
    # key            emoji  custom_emoji_id
    "rocket":        {"e": "🚀", "id": None},
    "fire":          {"e": "🔥", "id": None},
    "party":         {"e": "🎉", "id": None},
    "upload":        {"e": "📤", "id": None},
    "download":      {"e": "📥", "id": None},
    "cloud":         {"e": "☁️", "id": None},
    "folder":        {"e": "📁", "id": "5875206779196935950"},
    "doc":           {"e": "📄", "id": "5258477770735885832"},
    "link":          {"e": "🔗", "id": None},
    "video":         {"e": "🎬", "id": None},
    "audio":         {"e": "🎵", "id": None},
    "image":         {"e": "🖼", "id": None},
    "torrent":       {"e": "🧲", "id": None},
    "login":         {"e": "🔐", "id": None},
    "key":           {"e": "🔑", "id": None},
    "crown":         {"e": "👑", "id": None},
    "star":          {"e": "⭐️", "id": "5874948844935974490"},
    "diamond":       {"e": "💎", "id": "5807465992363710697"},
    "bolt":          {"e": "⚡️", "id": "5843553939672274145"},
    "check":         {"e": "✅", "id": "5920052658743283381"},
    "cross":         {"e": "❌", "id": "5258226313285607065"},
    "warn":          {"e": "⚠️", "id": None},
    "info":          {"e": "ℹ️", "id": None},
    "clock":         {"e": "⏰", "id": None},
    "gear":          {"e": "⚙️", "id": None},
    "home":          {"e": "🏠", "id": "5807868868886009920"},
    "back":          {"e": "⬅️", "id": "5877536313623711363"},
    "next":          {"e": "➡️", "id": None},
    "list":          {"e": "📋", "id": None},
    "search":        {"e": "🔍", "id": None},
    "trash":         {"e": "🗑", "id": None},
    "bell":          {"e": "🔔", "id": None},
    "lang":          {"e": "🌐", "id": None},
    "user":          {"e": "👤", "id": None},
    "lock":          {"e": "🔒", "id": None},
    "logout":        {"e": "🚪", "id": None},
    "stats":         {"e": "📊", "id": None},
    "speed":         {"e": "🏎", "id": None},
    "shield":        {"e": "🛡", "id": None},
    "gift":          {"e": "🎁", "id": None},
    "heart":         {"e": "❤️", "id": None},
    "pin":           {"e": "📌", "id": None},
    "code":          {"e": "💻", "id": None},
    "help":          {"e": "❓", "id": None},
    "bot":           {"e": "🤖", "id": None},
    "clip":          {"e": "📎", "id": "5305265301917549162"},
}

SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
DOTS = ("", ".", "..", "…")


class EmojiEngine:
    """Renders emoji tokens; flips to plain mode if Telegram refuses customs."""

    def __init__(self) -> None:
        self.catalog: dict[str, dict] = dict(DEFAULT_CATALOG)
        self.mode: str = settings.custom_emoji  # auto | on | off
        self._verified: set[str] = set()       # ids confirmed by Telegram
        self._dead_ids: set[str] = set()
        self.load()

    # ── catalogue ──────────────────────────────────────────────────────────
    def load(self) -> None:
        try:
            if CATALOG_FILE.exists():
                data = json.loads(CATALOG_FILE.read_text("utf-8"))
                for k, v in data.items():
                    if isinstance(v, dict) and v.get("e"):
                        self.catalog[k] = {"e": v["e"], "id": v.get("id")}
                log.info("Emoji catalogue: %d entries", len(self.catalog))
        except Exception as e:  # noqa: BLE001
            log.warning("Could not read emoji catalogue: %s", e)

    def save(self) -> None:
        CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CATALOG_FILE.write_text(
            json.dumps(self.catalog, indent=2, ensure_ascii=False), "utf-8"
        )

    def set_id(self, key: str, emoji: str, emoji_id: str) -> None:
        self.catalog[key] = {"e": emoji, "id": emoji_id}
        self._dead_ids.discard(emoji_id)
        self.save()

    # ── capability probing ─────────────────────────────────────────────────
    async def verify(self, bot) -> None:
        """Ask Telegram which catalogue ids actually exist / are usable."""
        if self.mode == "off":
            return
        ids = [v["id"] for v in self.catalog.values() if v.get("id")]
        if not ids:
            self.mode = "off"
            return
        try:
            stickers = await bot.get_custom_emoji_stickers(custom_emoji_ids=ids)
            self._verified = {s.custom_emoji_id for s in stickers if s.custom_emoji_id}
            missing = set(ids) - self._verified
            if missing:
                self._dead_ids |= missing
                log.warning("Emoji: %d id(s) unavailable, using fallbacks", len(missing))
            log.info("Emoji: %d/%d premium emojis verified ✔", len(self._verified), len(ids))
            self.mode = "on" if self._verified else "off"
        except Exception as e:  # noqa: BLE001
            log.warning("Emoji verification failed (%s) — plain emoji mode", e)
            self.mode = "off"

    def disable_custom(self, reason: str = "") -> None:
        if self.mode != "off":
            log.warning("Premium emoji disabled for this session %s", f"({reason})" if reason else "")
            self.mode = "off"

    @property
    def custom(self) -> bool:
        return self.mode == "on" and bool(self._verified)

    # ── rendering ──────────────────────────────────────────────────────────
    def raw(self, key: str) -> str:
        entry = self.catalog.get(key) or {"e": "•", "id": None}
        return entry["e"]

    def id_of(self, key: str) -> Optional[str]:
        entry = self.catalog.get(key) or {}
        eid = entry.get("id")
        if not eid or eid in self._dead_ids:
            return None
        if self.custom and self._verified and eid not in self._verified:
            return None
        return eid if self.custom else None

    def __call__(self, key: str) -> str:
        """`emoji('rocket')` → premium tag or plain fallback."""
        eid = self.id_of(key)
        fallback = self.raw(key)
        if not eid:
            return fallback
        return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'


emoji = EmojiEngine()


def t(template: str) -> str:
    """Render `{token}` placeholders in a message template.

    e.g. t("{rocket} <b>Done</b> — {check}") → premium-tagged HTML.
    Unknown tokens are left untouched.
    """
    if "{" not in template:
        return template
    out = []
    i = 0
    while i < len(template):
        if template[i] == "{":
            j = template.find("}", i)
            if j == -1:
                out.append(template[i:])
                break
            token = template[i + 1: j].strip()
            if token in emoji.catalog:
                out.append(emoji(token))
            else:
                out.append(template[i: j + 1])
            i = j + 1
        else:
            out.append(template[i])
            i += 1
    return "".join(out)


def icon(key: str) -> Optional[str]:
    """Custom emoji id for inline-button icons (None → plain text button)."""
    return emoji.id_of(key)


def spin(frame: int) -> str:
    return SPINNER[frame % len(SPINNER)]


def dots(frame: int) -> str:
    return DOTS[frame % len(DOTS)]
