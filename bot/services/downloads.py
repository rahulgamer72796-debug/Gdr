"""Download engine.

detect()   → figures out what a link *is* before we touch it
download() → streams it to disk with live progress

Supported out of the box:
  • direct http(s) files (any host, ranges, redirects, content-disposition names)
  • 1000+ media sites through yt-dlp (YouTube, Instagram, TikTok, X, …)
  • Google Drive links are handled by `drive.py` (server-side clone, no download)
  • Telegram posts/files are handled directly by the bot (copy/download)
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

import aiohttp

from ..config import settings
from ..logger import log
from ..utils import mime_for, safe_filename
from .common import CancelledTask, Progress

try:
    import yt_dlp  # noqa: N813
    HAS_YTDLP = True
except Exception:  # noqa: BLE001
    HAS_YTDLP = False

def _find_ffmpeg() -> Optional[str]:
    """System ffmpeg first, then the pip-packaged static build (imageio-ffmpeg).

    Without any ffmpeg, yt-dlp cannot mux separate video+audio streams, which
    silently caps YouTube at 360p. This makes 1080p work on any host.
    """
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg  # optional dependency
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and os.path.exists(exe) else None
    except Exception:  # noqa: BLE001
        return None


FFMPEG_PATH = _find_ffmpeg()
HAS_FFMPEG = bool(FFMPEG_PATH)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

MEDIA_HOSTS = (
    "youtube.com", "youtu.be", "music.youtube.com", "instagram.com", "tiktok.com",
    "twitter.com", "x.com", "facebook.com", "fb.watch", "vimeo.com", "dailymotion.com",
    "reddit.com", "soundcloud.com", "twitch.tv", "bilibili.com", "pinterest.com",
    "threads.net", "snapchat.com", "likee.video", "sharechat.com", "rumble.com",
    "terabox.com", "streamable.com", "ok.ru", "vk.com", "douyin.com", "kwai.com",
)

GDRIVE_PATTERNS = (
    re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_-]{10,})"),
    re.compile(r"drive\.google\.com/open\?id=([A-Za-z0-9_-]{10,})"),
    re.compile(r"drive\.google\.com/uc\?.*?id=([A-Za-z0-9_-]{10,})"),
    re.compile(r"drive\.google\.com/drive/folders/([A-Za-z0-9_-]{10,})"),
    re.compile(r"docs\.google\.com/\w+/d/([A-Za-z0-9_-]{10,})"),
)


class DownloadError(Exception):
    pass


def friendly_ytdlp_error(raw: str, url: str = "") -> str:
    """Turn yt-dlp's wall of text into something a Telegram user can act on."""
    low = (raw or "").lower()
    if "sign in to confirm you" in low or "confirm you\u2019re not a bot" in low:
        return ("YouTube is asking this server to prove it's human (it happens on most "
                "datacenter IPs). Fix: send me a `cookies.txt` — owner can upload it with "
                "/cookies — or set YTDL_COOKIES_FILE in .env. Other sites are unaffected.")
    if "age" in low and ("restrict" in low or "confirm your age" in low):
        return "This video is age-restricted — it needs a logged-in cookies.txt to download."
    if "private video" in low or "this video is private" in low:
        return "That video is private — nobody can download it without access."
    if "members-only" in low or "join this channel" in low:
        return "Members-only video — needs an account with that membership (cookies)."
    if "video unavailable" in low or "removed by the uploader" in low:
        return "The video is unavailable (deleted, region-blocked or geo-restricted)."
    if "unsupported url" in low:
        return "yt-dlp doesn't support that site — send a direct file link instead."
    if "is not a valid url" in low:
        return "That doesn't look like a valid link."
    if "timed out" in low or "timeout" in low:
        return "The site took too long to respond — try again in a moment."
    if "http error 403" in low:
        return "The site refused the download (403) — it may need cookies or a referer."
    if "ffmpeg" in low:
        return "ffmpeg is missing, so video+audio can't be merged. Install ffmpeg on the host."
    first = next((ln for ln in (raw or "").splitlines() if ln.strip()), "")
    return f"Download failed: {first[:180]}"


# ══════════════════════════════════════════════════════════════════════════
#  Source detection
# ══════════════════════════════════════════════════════════════════════════
def gdrive_id(url: str) -> Optional[str]:
    for pat in GDRIVE_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def is_gdrive(url: str) -> bool:
    return bool(gdrive_id(url))


def is_media_site(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in MEDIA_HOSTS)


def _filename_from(url: str, disposition: str = "") -> str:
    if disposition:
        m = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.I)
        if m:
            return safe_filename(unquote(m.group(1)).strip('"'))
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if not name or "." not in name:
        name = (name or "download") + ".bin" if not name else name
    return safe_filename(name, "download")


async def probe(session: aiohttp.ClientSession, url: str) -> dict:
    """Lightweight look at a URL: content type, size, filename."""
    info = {"url": url, "type": "", "size": 0, "name": _filename_from(url)}
    try:
        headers = {"User-Agent": UA, "Accept": "*/*"}
        async with session.get(url, headers=headers, allow_redirects=True,
                               timeout=aiohttp.ClientTimeout(total=25, sock_read=25)) as r:
            if r.status >= 400:
                raise DownloadError(f"The server answered {r.status} — link may be dead or private.")
            info["type"] = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            info["size"] = int(r.headers.get("Content-Length") or 0)
            info["name"] = _filename_from(str(r.url), r.headers.get("Content-Disposition", ""))
    except aiohttp.ClientError as e:
        raise DownloadError(f"Could not reach the link: {e}") from e
    return info


# ══════════════════════════════════════════════════════════════════════════
#  Streaming HTTP download
# ══════════════════════════════════════════════════════════════════════════
async def download_http(session: aiohttp.ClientSession, url: str, dest: Path,
                        progress: Progress) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": UA, "Accept": "*/*"}
    timeout = aiohttp.ClientTimeout(total=None, sock_read=120)

    async with session.get(url, headers=headers, timeout=timeout) as r:
        if r.status >= 400:
            raise DownloadError(f"The server answered {r.status} — link may be dead or private.")
        total = int(r.headers.get("Content-Length") or 0)
        name = _filename_from(str(r.url), r.headers.get("Content-Disposition", ""))
        out = dest / name
        progress.update(name=name, total=total, phase="downloading")
        done = 0
        with out.open("wb") as fh:
            async for chunk in r.content.iter_chunked(256 * 1024):
                if progress.cancelled:
                    raise CancelledTask()
                fh.write(chunk)
                done += len(chunk)
                progress.update(done=done, total=total or None)
        if out.stat().st_size == 0:
            raise DownloadError("Downloaded file is empty (server returned nothing).")
        return [out]


# ══════════════════════════════════════════════════════════════════════════
#  yt-dlp download (runs in a worker thread)
# ══════════════════════════════════════════════════════════════════════════
def _quality_format(q: str) -> str:
    q = (q or "best").lower()
    if q == "audio":
        return "bestaudio/best"
    if q.isdigit():
        return (f"bestvideo[height<={q}]+bestaudio/best[height<={q}]/best")
    return "bestvideo*+bestaudio/best"


def _ytdlp_download(url: str, dest: Path, quality: str, progress: Progress) -> list[Path]:
    if not HAS_YTDLP:
        raise DownloadError("This link needs yt-dlp (media site support), but it isn't installed.")

    def hook(d: dict) -> None:
        if progress.cancelled:
            raise CancelledTask()
        if d.get("status") == "downloading":
            progress.update(
                done=int(d.get("downloaded_bytes") or 0),
                total=int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0),
                phase="downloading",
                name=d.get("filename") and Path(str(d["filename"])).name or "",
            )
        elif d.get("status") == "finished":
            progress.update(done=progress.total or None, phase="processing",
                            note="Merging streams…" if HAS_FFMPEG else "Finalising…")

    opts = {
        "outtmpl": str(dest / "%(title).150B.%(ext)s"),
        "http_headers": {"User-Agent": UA},
        "format": _quality_format(quality),
        "noplaylist": False,
        "playlist_items": "1-50",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "concurrent_fragment_downloads": 4,
        "retries": 3,
        "progress_hooks": [hook],
        "restrictfilenames": False,
        "windowsfilenames": True,
        "overwrites": True,
    }
    # Authenticated/age-restricted sources: cookies unlock YouTube's bot check.
    if settings.ytdl_cookies.exists():
        opts["cookiefile"] = str(settings.ytdl_cookies)
    if settings.ytdl_cookie_browser:
        opts["cookiesfrombrowser"] = (settings.ytdl_cookie_browser,)

    if HAS_FFMPEG:
        opts["merge_output_format"] = "mp4"
        if FFMPEG_PATH and not shutil.which("ffmpeg"):
            opts["ffmpeg_location"] = str(Path(FFMPEG_PATH).parent)
    else:
        opts["format"] = ("best[ext=mp4]/best" if quality not in ("audio",)
                          else "bestaudio[ext=m4a]/bestaudio/best")

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(friendly_ytdlp_error(str(e), url)) from e
    except Exception as e:  # noqa: BLE001  (yt-dlp raises raw network errors too)
        name = type(e).__name__
        if any(k in name for k in ("RequestError", "InvalidURL", "ConnectionError",
                                   "NetworkError", "Timeout", "SSLError")):
            raise DownloadError(
                f"Couldn't open that link ({name}). Check the URL is complete and reachable."
            ) from e
        raise
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            paths = [Path(ydl.prepare_filename(e)) for e in entries]
        else:
            paths = [Path(ydl.prepare_filename(info))]

    found: list[Path] = []
    for p in paths:
        if p.exists():
            found.append(p)
        else:  # extension may have changed after merge
            for cand in dest.glob(p.stem + ".*"):
                found.append(cand)
                break
    if not found:
        # last resort: newest file in the directory
        files = sorted(dest.glob("*"), key=os.path.getmtime, reverse=True)
        found = files[:1]
    if not found:
        raise DownloadError("The media site returned no downloadable file.")
    return found


async def download_media(url: str, dest: Path, quality: str, progress: Progress) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    return await asyncio.to_thread(_ytdlp_download, url, dest, quality, progress)


# ══════════════════════════════════════════════════════════════════════════
#  Public façade
# ══════════════════════════════════════════════════════════════════════════
async def download(session: aiohttp.ClientSession, url: str, dest: Path, progress: Progress,
                   quality: str = "best") -> list[Path]:
    """Download `url` into `dest`, choosing the right strategy automatically."""
    dest.mkdir(parents=True, exist_ok=True)
    if is_media_site(url):
        log.info("yt-dlp → %s", url)
        return await download_media(url, dest, quality, progress)

    try:
        info = await probe(session, url)
    except DownloadError:
        if HAS_YTDLP:                      # maybe a media page behind a shady host
            return await download_media(url, dest, quality, progress)
        raise

    size = info["size"]
    if size and settings.max_file_gb and size > settings.max_file_gb * 1024 ** 3:
        raise DownloadError(
            f"File is {size / 1024 ** 3:.2f} GB — bigger than this bot's "
            f"{settings.max_file_gb:g} GB limit (set MAX_FILE_GB to raise it).")

    if info["type"] in ("text/html", "application/xhtml+xml") and HAS_YTDLP:
        log.info("HTML page → trying yt-dlp: %s", url)
        try:
            return await download_media(url, dest, quality, progress)
        except Exception as e:  # noqa: BLE001
            log.warning("yt-dlp could not handle %s: %s", url, e)
            raise DownloadError("This page isn't a direct file and no video was found on it.") from e

    progress.update(name=info["name"], total=size, phase="downloading")
    return await download_http(session, url, dest, progress)


def guess_is_archive(name: str) -> bool:
    return Path(name).suffix.lower() in (".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2")


def mime_of(name: str, header_type: str = "") -> str:
    return mime_for(name, header_type or None)
