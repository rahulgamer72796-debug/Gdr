"""Generic helpers: formatting, security, url sniffing."""
from __future__ import annotations

import html
import re
import time
from typing import Optional
from urllib.parse import urlparse

# ── formatting ─────────────────────────────────────────────────────────────
_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_size(n: Optional[float]) -> str:
    """Accepts int/float/str/None — APIs (Google Drive!) love returning strings."""
    if n is None or n == "":
        return "—"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    if n < 0:
        return "—"
    for u in _UNITS:
        if n < 1024 or u == _UNITS[-1]:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.2f} {u}"
        n /= 1024
    return f"{n:.2f} PB"


def human_time(seconds: Optional[float]) -> str:
    if not seconds or seconds < 0 or seconds == float("inf"):
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d {h:02d}h"


def eta(remaining_bytes: Optional[float], speed: Optional[float]) -> str:
    if not remaining_bytes or not speed:
        return "—"
    return human_time(remaining_bytes / speed)


def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def clip(text: str, limit: int = 60) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def bar(percent: float, width: int = 12) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = round(percent / 100 * width)
    return "▰" * filled + "▱" * (width - filled)


def pct(done: float, total: float) -> float:
    return 100.0 if not total else min(100.0, max(0.0, done / total * 100))


def short_id(value: str, n: int = 6) -> str:
    return (value or "")[:n]


# ── security ───────────────────────────────────────────────────────────────
_BAD_SCHEMES = {"javascript", "data", "file", "ftp", "vbscript"}


def safe_url(url: str) -> Optional[str]:
    """Normalise + validate an http(s) URL. Returns None if it's not safe."""
    if not url:
        return None
    url = url.strip().strip("<>\"'")
    # Reject any explicit non-http scheme *before* we normalise
    scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):", url)
    if scheme_match and scheme_match.group(1).lower() not in ("http", "https"):
        return None
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme.lower() in _BAD_SCHEMES or not parsed.netloc:
        return None
    if re.search(r"[\s]", url):
        return None
    return url


TG_LINK = re.compile(
    r"^(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/(?:c/)?"
    r"([A-Za-z0-9_]+|\d+)/(\d+)(?:\?single)?/?$",
    re.I,
)
TG_PRIVATE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/c/(\d+)/(\d+)/?$", re.I)


def parse_tg_link(url: str) -> Optional[tuple[str, int]]:
    """t.me/username/123 · t.me/c/1234/5 → (chat_ref, message_id)."""
    m = TG_LINK.match(url.strip())
    if not m:
        return None
    chat, mid = m.group(1), int(m.group(2))
    if chat.isdigit():  # /c/ form → internal -100 prefix
        chat = f"-100{chat}"
    return chat, mid


def safe_filename(name: str, fallback: str = "file") -> str:
    name = (name or "").replace("\x00", "").strip()
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name)
    name = name.lstrip(". ") or fallback
    return name[:180]


MIME_BY_EXT = {
    "mp4": "video/mp4", "mkv": "video/x-matroska", "avi": "video/x-msvideo",
    "webm": "video/webm", "mov": "video/quicktime", "mp3": "audio/mpeg",
    "m4a": "audio/mp4", "flac": "audio/flac", "wav": "audio/wav", "opus": "audio/ogg",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "pdf": "application/pdf", "zip": "application/zip",
    "rar": "application/vnd.rar", "7z": "application/x-7z-compressed",
    "tar": "application/x-tar", "gz": "application/gzip", "apk": "application/vnd.android.package-archive",
    "exe": "application/x-msdownload", "txt": "text/plain", "json": "application/json",
    "srt": "application/x-subrip", "vtt": "text/vtt", "iso": "application/x-iso9660-image",
}


def mime_for(name: str, from_header: Optional[str] = None) -> str:
    if from_header and "/" in from_header and len(from_header) < 100:
        return from_header.split(";")[0].strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return MIME_BY_EXT.get(ext, "application/octet-stream")


def youtube_id(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def now() -> float:
    return time.time()
