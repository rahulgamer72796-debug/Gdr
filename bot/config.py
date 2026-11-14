"""Configuration — .env driven, validated, single source of truth."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default) or default)
    return p if p.is_absolute() else (ROOT / p)


@dataclass
class Settings:
    # Telegram
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()
    owner_id: int = _int("OWNER_ID", 0)
    bot_name: str = os.getenv("BOT_NAME", "MirrorX")
    bot_username: str = os.getenv("BOT_USERNAME", "")
    support_group: str = os.getenv("SUPPORT_GROUP", "https://t.me/PublicMirrorLeechGroup")
    update_channel: str = os.getenv("UPDATE_CHANNEL", "https://t.me/PublicBotsHub")
    owner_contact: str = os.getenv("OWNER_CONTACT", "")

    # Google Drive
    client_id: str = os.getenv("GDRIVE_CLIENT_ID", "").strip()
    client_secret: str = os.getenv("GDRIVE_CLIENT_SECRET", "").strip() or "x"  # device flow needs a secret; Google ignores its value
    gdrive_folder_id: str = os.getenv("GDRIVE_FOLDER_ID", "").strip()
    _sa_json: str = os.getenv("GDRIVE_SA_JSON", "").strip()
    sa_file: Path = _path("GDRIVE_SA_FILE", "data/service_account.json")

    # Storage / limits
    download_dir: Path = _path("DOWNLOAD_DIR", "downloads")
    max_concurrent: int = max(1, _int("MAX_CONCURRENT_TASKS", 2))
    leech_confirm_mb: int = _int("LEECH_CONFIRM_MB", 360)
    max_file_gb: float = _float("MAX_FILE_GB", 15.0)
    auto_cleanup: bool = _bool("AUTO_CLEANUP", True)

    # Feel / look
    custom_emoji: str = os.getenv("CUSTOM_EMOJI", "auto").lower()
    default_quality: str = os.getenv("DEFAULT_QUALITY", "best")
    message_effects: bool = _bool("MESSAGE_EFFECTS", True)
    progress_interval: float = max(2.0, _float("PROGRESS_INTERVAL", 4.0))

    # Log / activity channel (lock channel) — every user activity lands here.
    # Format: -100xxxxxxxxxx  (bot must be ADMIN in that channel)
    log_channel_id: int = _int("LOG_CHANNEL_ID", 0)
    log_new_users: bool = _bool("LOG_NEW_USERS", True)
    log_tasks: bool = _bool("LOG_TASKS", True)
    log_admins: bool = _bool("LOG_ADMIN_ACTIONS", True)

    # yt-dlp
    ytdl_cookies: Path = _path("YTDL_COOKIES_FILE", "data/cookies.txt")
    ytdl_cookie_browser: str = os.getenv("YTDL_COOKIES_FROM_BROWSER", "").strip()

    # Internals
    db_path: Path = _path("DATABASE_PATH", "data/mirrorx.db")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    def __post_init__(self) -> None:
        # make sure our working directories exist before anything touches them
        for d in (self.download_dir, self.db_path.parent, self.sa_file.parent):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    # ── derived ────────────────────────────────────────────────────────────
    @property
    def oauth_enabled(self) -> bool:
        return bool(self.client_id)

    @property
    def sa_path(self) -> Path | None:
        if self.sa_file.exists():
            return self.sa_file
        if self._sa_json:
            try:
                data = json.loads(self._sa_json)
                self.sa_file.parent.mkdir(parents=True, exist_ok=True)
                self.sa_file.write_text(json.dumps(data, indent=2))
                return self.sa_file
            except json.JSONDecodeError:
                return None
        return None

    @property
    def logging_enabled(self) -> bool:
        return bool(self.log_channel_id)

    @property
    def masked_token(self) -> str:
        t = self.bot_token
        if not t:
            return "(not set)"
        return f"{t.split(':')[0]}:***{t[-4:]}" if ":" in t else "***"

    @property
    def share_links(self) -> list[tuple[str, str]]:
        links = [("💬 Support", self.support_group), ("📣 Channel", self.update_channel)]
        if self.owner_contact.startswith("@"):
            links.append(("👤 Owner", f"https://t.me/{self.owner_contact[1:]}"))
        return links

    def validate(self) -> list[str]:
        p: list[str] = []
        if not self.bot_token or ":" not in self.bot_token:
            p.append("BOT_TOKEN is missing or malformed (get one from @BotFather).")
        if not self.owner_id:
            p.append("OWNER_ID is not set — nobody will have admin rights.")
        if self.log_channel_id and not str(self.log_channel_id).startswith("-100"):
            p.append("LOG_CHANNEL_ID looks wrong — a channel id starts with -100…")
        if not self.oauth_enabled and not self.sa_path:
            p.append("No Google Drive access configured: set GDRIVE_CLIENT_ID/SECRET "
                     "(email login) or GDRIVE_SA_JSON (service account).")
        if not self.oauth_enabled:
            p.append("GDRIVE_CLIENT_ID missing — the 'Login with Google' flow is disabled.")
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            probe = self.download_dir / ".write_test"
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            p.append(f"DOWNLOAD_DIR is not writable: {e}")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
