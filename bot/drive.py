"""Google Drive engine — hardened for very large files (10 GB+).

Authorisation, exactly like the big mirror bots:

1. **Email login (OAuth 2.0 Device Flow)** — the user opens a Google page, types
   a short code and their *own* Drive becomes the destination. Works headless.
2. **Service account (bot-wide)** — one JSON key, one shared drive.

Uploads use the resumable endpoint properly:
  • chunk sizes are multiples of 256 KiB (Google requirement), scaled by file size
  • `308 Resume Incomplete` is honoured, including *partial* chunks — the file
    handle is re-seeked to Google's acknowledged offset, so bytes never drift
    (this is what keeps a 10 GB upload byte-exact)
  • network drops and 5xx re-query the session for the committed offset and
    continue instead of restarting
  • an expired session is re-opened and restarted cleanly
  • every loop checks a cancel hook, so a 10 GB upload can be stopped instantly
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiohttp
import jwt

from .config import settings
from .db import db
from .logger import log

SCOPE = "https://www.googleapis.com/auth/drive"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
API_URL = "https://www.googleapis.com/drive/v3/files"
ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
FOLDER_MIME = "application/vnd.google-apps.folder"

KIB256 = 256 * 1024
MAX_SESSION_REOPENS = 2
MAX_CHUNK_ATTEMPTS = 6

ProgressCb = Callable[[float, float], Awaitable[None]]   # (done_bytes, total_bytes)
CancelCb = Callable[[], bool]


class DriveError(Exception):
    """Human-readable Drive failure (message is shown to the user)."""


class AuthExpired(DriveError):
    pass


class UploadCancelled(Exception):
    """The user cancelled while we were uploading."""


def plan_chunk(size: int) -> int:
    """Chunk size: always a multiple of 256 KiB, scaled to keep request count sane.

    < 256 MiB →  8 MiB  (≈ 32 requests/GiB)
    < 2 GiB   → 32 MiB
    ≥ 2 GiB   → 64 MiB  (a 10 GiB file = ~160 requests)
    """
    if size <= 256 * 1024**2:
        return 8 * 1024**2
    if size <= 2 * 1024**3:
        return 32 * 1024**2
    return 64 * 1024**2


def _friendly(status: int, body: str) -> str:
    """Translate Drive's JSON errors into something a human can act on."""
    reason = ""
    try:
        err = json.loads(body or "{}").get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "") or err.get("status", "")
        message = err.get("message", "")
    except (json.JSONDecodeError, AttributeError, IndexError):
        message = ""
    low = f"{reason} {message}".lower()
    if "storagequotaexceeded" in low or "storage quota" in low:
        return "Your Google Drive is full — free up space (or use another account) and retry."
    if "userratelimitexceeded" in low or "ratelimitexceeded" in low:
        return "Google is throttling this account right now. Try again in a few minutes."
    if "dailyLimitExceeded" in reason or "uploadlimitexceeded" in low:
        return ("You've hit Google's daily upload limit (750 GB per account per day). "
                "It resets ~24 h after the first upload; nothing is lost, just retry later.")
    if "notfound" in low or status == 404:
        return "Drive says that folder/file doesn't exist (was it deleted, or not shared)?"
    if "insufficientfilepermissions" in low or "forbidden" in low or status == 403:
        return ("This Google account can't write there. For a service account, share the "
                "target folder with the service-account e-mail as Editor.")
    if status == 413:
        return "Google rejected a chunk as too large."
    if status == 401:
        return "Google login expired — reconnect with /login."
    detail = (message or reason or body or "").strip()[:180]
    return f"Drive API error {status}: {detail}"


# ══════════════════════════════════════════════════════════════════════════
#  OAuth device flow
# ══════════════════════════════════════════════════════════════════════════
async def start_device_login(session: aiohttp.ClientSession) -> dict:
    if not settings.oauth_enabled:
        raise DriveError("Email login isn't configured on this bot (missing GDRIVE_CLIENT_ID).")
    data = {
        "client_id": settings.client_id,
        "scope": SCOPE,
        "device_id": "mirrorx-bot",
        "device_model": settings.bot_name,
    }
    async with session.post(DEVICE_URL, data=data) as resp:
        body = await resp.json(content_type=None)
        if resp.status != 200:
            err = body.get("error_description") or body.get("error") or resp.status
            raise DriveError(f"Google refused the login request: {err}")
    return body


async def poll_device_token(session: aiohttp.ClientSession, device_code: str) -> Optional[dict]:
    data = {
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    async with session.post(TOKEN_URL, data=data) as resp:
        body = await resp.json(content_type=None)
        if resp.status == 200:
            return body
        err = body.get("error")
        if err in ("authorization_pending", "slow_down"):
            return None
        if err == "access_denied":
            raise DriveError("You denied the login on Google.")
        if err == "expired_token":
            raise DriveError("The login code expired — start again.")
        raise DriveError(body.get("error_description") or err or "Google login failed")


async def refresh_access_token(session: aiohttp.ClientSession, refresh_token: str) -> dict:
    data = {
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with session.post(TOKEN_URL, data=data) as resp:
        body = await resp.json(content_type=None)
        if resp.status != 200:
            raise AuthExpired("Google session expired — please reconnect your Drive.")
    return body


async def oauth_userinfo(session: aiohttp.ClientSession, access_token: str) -> dict:
    async with session.get(USERINFO_URL,
                           headers={"Authorization": f"Bearer {access_token}"}) as resp:
        if resp.status != 200:
            return {}
        return await resp.json(content_type=None)


# ══════════════════════════════════════════════════════════════════════════
#  Service account
# ══════════════════════════════════════════════════════════════════════════
_sa_cache: dict = {"token": "", "exp": 0.0}


async def service_account_token(session: aiohttp.ClientSession) -> str:
    path = settings.sa_path
    if not path:
        raise DriveError("Service account isn't configured on this bot.")
    if _sa_cache["token"] and _sa_cache["exp"] - 60 > time.time():
        return _sa_cache["token"]
    try:
        info = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise DriveError(f"Service-account file is unreadable: {e}") from e
    now = int(time.time())
    claims = {"iss": info["client_email"], "scope": SCOPE, "aud": TOKEN_URL,
              "iat": now, "exp": now + 3600}
    try:
        assertion = jwt.encode(claims, info["private_key"], algorithm="RS256")
    except Exception as e:  # noqa: BLE001
        raise DriveError(f"Could not sign service-account token: {e}") from e
    async with session.post(TOKEN_URL, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }) as resp:
        body = await resp.json(content_type=None)
        if resp.status != 200:
            raise DriveError(_friendly(resp.status, json.dumps(body)))
    _sa_cache["token"] = body["access_token"]
    _sa_cache["exp"] = time.time() + int(body.get("expires_in", 3600))
    return _sa_cache["token"]


# ══════════════════════════════════════════════════════════════════════════
#  Per-user Drive client
# ══════════════════════════════════════════════════════════════════════════
class Drive:
    def __init__(self, session: aiohttp.ClientSession, user_id: int, mode: str,
                 fallback_folder: str = "") -> None:
        self.session = session
        self.user_id = user_id
        self.mode = mode                # oauth | sa
        self.folder_id = fallback_folder or settings.gdrive_folder_id
        self._token: str = ""
        self._exp: float = 0.0
        self._lock = asyncio.Lock()

    # ── auth ───────────────────────────────────────────────────────────────
    async def access_token(self, force: bool = False) -> str:
        async with self._lock:
            if self.mode == "sa":
                return await service_account_token(self.session)
            if self._token and not force and self._exp - 90 > time.time():
                return self._token
            tok = await db.get_token(self.user_id)
            if not tok:
                raise AuthExpired("No Google account connected — use /login first.")
            if tok["access_token"] and tok["expires_at"] - 90 > time.time() and not force:
                self._token, self._exp = tok["access_token"], tok["expires_at"]
                return self._token
            if not tok["refresh_token"]:
                raise AuthExpired("Google session expired — reconnect your Drive with /login.")
            fresh = await refresh_access_token(self.session, tok["refresh_token"])
            self._token = fresh["access_token"]
            self._exp = time.time() + int(fresh.get("expires_in", 3600))
            await db.set_token(self.user_id, tok["email"], self._token,
                               tok["refresh_token"], self._exp, account="oauth")
            log.info("Refreshed Google token for user %s", self.user_id)
            return self._token

    async def _request(self, method: str, url: str, *, params: dict | None = None,
                       json_body: dict | None = None, expect: tuple = (200, 201)) -> dict:
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {await self.access_token()}",
                       "Content-Type": "application/json; charset=UTF-8"}
            async with self.session.request(method, url, params=params, json=json_body,
                                            headers=headers) as resp:
                text = await resp.text()
                if resp.status == 401 and attempt == 0:
                    await self.access_token(force=True)
                    continue
                if resp.status not in expect:
                    raise DriveError(_friendly(resp.status, text))
                try:
                    return json.loads(text) if text else {}
                except json.JSONDecodeError:
                    return {}
        raise DriveError("Drive API authentication failed after a token refresh.")

    # ── account ────────────────────────────────────────────────────────────
    async def about(self) -> dict:
        body = await self._request(
            "GET", ABOUT_URL,
            params={"fields": "user(displayName,emailAddress),storageQuota(limit,usage)"})
        # Google returns quota numbers as *strings*; normalise so every consumer
        # (cards, arithmetic, sorting) gets real ints.
        quota = body.get("storageQuota") or {}
        for key in ("limit", "usage"):
            if key in quota:
                try:
                    quota[key] = int(quota[key])
                except (TypeError, ValueError):
                    quota.pop(key, None)
        body["storageQuota"] = quota
        return body

    # ── folders ────────────────────────────────────────────────────────────
    async def create_folder(self, name: str, parent: str = "") -> str:
        meta = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            meta["parents"] = [parent]
        body = await self._request("POST", API_URL, params={"fields": "id"}, json_body=meta)
        return body["id"]

    async def find_child_folder(self, name: str, parent: str = "") -> Optional[str]:
        safe = name.replace("'", "\\'")
        q = (f"name='{safe}' and mimeType='{FOLDER_MIME}' and trashed=false "
             f"and '{parent or 'root'}' in parents")
        body = await self._request("GET", API_URL,
                                   params={"q": q, "fields": "files(id,name)", "pageSize": "1"})
        files = body.get("files") or []
        return files[0]["id"] if files else None

    async def ensure_path(self, base: str, relative: str) -> str:
        """Create (or reuse!) `base/relative` → returns the leaf folder id.

        Reusing existing folders matters: without it every 10 GB re-run would
        scatter duplicate `Season 1` folders across the user's Drive.
        """
        current = base
        for part in [p for p in relative.split("/") if p]:
            existing = await self.find_child_folder(part, current)
            current = existing or await self.create_folder(part, current)
        return current

    # ── resumable upload ───────────────────────────────────────────────────
    async def _open_session(self, meta: dict, mime: str, size: int) -> str:
        for attempt in (0, 1):
            token = await self.access_token(force=attempt == 1)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": mime,
                "X-Upload-Content-Length": str(size),
            }
            async with self.session.post(
                    f"{UPLOAD_URL}?uploadType=resumable&fields=id,name,size,webViewLink",
                    json=meta, headers=headers) as resp:
                text = await resp.text()
                if resp.status in (200, 201):
                    uri = resp.headers.get("Location")
                    if not uri:
                        raise DriveError("Drive didn't return an upload session URL.")
                    return uri
                if resp.status == 401 and attempt == 0:
                    continue
                raise DriveError(_friendly(resp.status, text))
        raise DriveError("Could not open an upload session (auth).")

    async def _query_committed(self, session_uri: str, size: int) -> int:
        """Ask Drive how many bytes of this session it actually has (0 if unknown)."""
        try:
            async with self.session.put(
                    session_uri, data=b"",
                    headers={"Content-Range": f"bytes */{size}"}) as r:
                if r.status in (200, 201):
                    return size
                rng = r.headers.get("Range")
                if rng and "-" in rng:
                    return int(rng.split("-")[1]) + 1
        except (aiohttp.ClientError, ValueError) as e:
            log.debug("committed-offset query failed: %s", e)
        return 0

    async def upload_file(self, path: Path, folder_id: str = "", name: str = "",
                          mime: str = "application/octet-stream",
                          progress: Optional[ProgressCb] = None,
                          should_cancel: Optional[CancelCb] = None) -> dict:
        size = path.stat().st_size
        meta: dict = {"name": name or path.name}
        target = folder_id or self.folder_id
        if target:
            meta["parents"] = [target]

        session_uri = await self._open_session(meta, mime, size)
        chunk_size = plan_chunk(size)
        committed = 0
        reopens = 0
        filename = meta["name"]

        # Progress must never move backwards: a resume or a re-opened session can
        # legitimately lower `committed`, but a bar that jumps back reads as broken.
        reported = 0

        async def _report(done: int) -> None:
            nonlocal reported
            reported = max(reported, min(int(done), size))
            if progress:
                await progress(reported, size)

        log.info("Upload %s (%s bytes, %s MiB chunks) → Drive",
                 filename, size, chunk_size // 1024**2)

        with path.open("rb") as fh:
            attempts = 0
            while committed < size:
                if should_cancel and should_cancel():
                    raise UploadCancelled()

                # Re-seek EVERY time: after a partial 308, Google may have kept
                # fewer bytes than we sent. Without this the stream drifts and
                # a large upload silently corrupts.
                fh.seek(committed)
                data = fh.read(min(chunk_size, size - committed))
                if not data:
                    raise DriveError("Unexpected end of file while uploading.")
                start, end = committed, committed + len(data) - 1

                try:
                    async with self.session.put(
                            session_uri, data=data,
                            headers={"Content-Length": str(len(data)),
                                     "Content-Range": f"bytes {start}-{end}/{size}"}) as r:
                        body = await r.text()
                        if r.status in (200, 201):
                            await _report(size)
                            try:
                                done = json.loads(body) if body else {}
                            except json.JSONDecodeError:
                                done = {}
                            log.info("Upload complete: %s (%s)", filename, done.get("id", "?"))
                            return done or {"id": "", "name": filename, "size": str(size)}
                        if r.status == 308:
                            rng = r.headers.get("Range")
                            acked = (int(rng.split("-")[1]) + 1
                                     if rng and "-" in rng else end + 1)
                            # never move backwards past what we sent, never overshoot
                            committed = max(committed, min(acked, size))
                            attempts = 0
                            await _report(committed)
                            continue
                        if r.status == 401:
                            await self.access_token(force=True)
                            attempts += 1
                            continue
                        if r.status in (404, 410) and reopens < MAX_SESSION_REOPENS:
                            reopens += 1
                            log.warning("Upload session expired — reopening (%d/%d)",
                                        reopens, MAX_SESSION_REOPENS)
                            session_uri = await self._open_session(meta, mime, size)
                            committed = 0
                            attempts = 0
                            await _report(0)      # clamped → displayed bar holds steady
                            continue
                        if r.status in (429, 500, 502, 503, 504):
                            raise _Retryable(r.status, body)
                        raise DriveError(_friendly(r.status, body))

                except (aiohttp.ClientError, asyncio.TimeoutError, _Retryable) as e:
                    attempts += 1
                    if attempts > MAX_CHUNK_ATTEMPTS:
                        extra = f" ({e})" if isinstance(e, _Retryable) else ""
                        raise DriveError(
                            f"Upload of {filename} failed after {MAX_CHUNK_ATTEMPTS} attempts at "
                            f"{committed / 1024**3:.2f} GB{extra}. The connection or Google is "
                            f"struggling — retry, the file is safe on disk.") from e
                    backoff = min(30, 1.5 * (2 ** (attempts - 1)))
                    log.warning("Chunk %s failed (%s) — resyncing in %.1fs",
                                f"{start}-{end}", type(e).__name__, backoff)
                    await asyncio.sleep(backoff)
                    acked = await self._query_committed(session_uri, size)
                    if acked >= size:
                        return {"id": "", "name": filename, "size": str(size)}
                    committed = max(committed, acked)
                    await _report(committed)

        return {"id": "", "name": filename, "size": str(size)}

    # ── list / meta / delete / copy ────────────────────────────────────────
    async def list_files(self, folder_id: str = "", page_token: str = "",
                         page_size: int = 20, query: str = "") -> dict:
        q = query or f"'{folder_id or 'root'}' in parents and trashed=false"
        return await self._request("GET", API_URL, params={
            "q": q, "pageSize": str(page_size), "pageToken": page_token,
            "orderBy": "modifiedTime desc",
            "fields": "nextPageToken,files(id,name,mimeType,size,webViewLink,modifiedTime)",
        })

    async def get_meta(self, file_id: str) -> dict:
        return await self._request("GET", f"{API_URL}/{file_id}",
                                   params={"fields": "id,name,size,webViewLink,mimeType,parents"})

    async def delete(self, file_id: str) -> None:
        await self._request("DELETE", f"{API_URL}/{file_id}", expect=(200, 204))

    async def copy(self, file_id: str, parent: str = "", name: str = "") -> dict:
        meta: dict = {}
        if parent:
            meta["parents"] = [parent]
        if name:
            meta["name"] = name
        return await self._request("POST", f"{API_URL}/{file_id}/copy",
                                   params={"fields": "id,name,size,webViewLink"}, json_body=meta)

    async def is_folder(self, file_id: str) -> bool:
        try:
            meta = await self.get_meta(file_id)
        except DriveError:
            return False
        return (meta.get("mimeType") or "").endswith("folder")


async def copy_tree(drive: Drive, source_id: str, dest_parent: str = "",
                    report: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
                    max_files: int = 2000) -> dict:
    """Recursively clone a Drive folder server-side (no bytes leave Google).

    Returns {"files": n, "folders": n, "root": dest_folder_id}.
    """
    created_root = await drive.create_folder("Cloned folder", dest_parent)
    stats = {"files": 0, "folders": 0, "root": created_root}

    async def walk(src: str, dst: str, depth: int) -> None:
        if depth > 8:
            return
        token = ""
        while True:
            body = await drive.list_files(folder_id=src, page_token=token, page_size=100)
            for item in body.get("files") or []:
                if stats["files"] + stats["folders"] >= max_files:
                    raise DriveError(f"Folder has more than {max_files} items — clone aborted "
                                     f"(raise the cap in drive.copy_tree if you really need it).")
                if (item.get("mimeType") or "").endswith("folder"):
                    sub = await drive.create_folder(item["name"], dst)
                    stats["folders"] += 1
                    await walk(item["id"], sub, depth + 1)
                else:
                    await drive.copy(item["id"], dst)
                    stats["files"] += 1
                    if report:
                        await report(item["name"], stats["files"],
                                     max(stats["files"], 1))
            token = body.get("nextPageToken") or ""
            if not token:
                break

    await walk(source_id, created_root, 0)
    return stats


class _Retryable(Exception):
    """Internal marker for 429/5xx responses."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}")


# ══════════════════════════════════════════════════════════════════════════
#  Tree upload (single file or a whole folder)
# ══════════════════════════════════════════════════════════════════════════
async def upload_tree(drive: Drive, root: Path, folder_id: str = "",
                      progress: Optional[ProgressCb] = None,
                      report: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
                      should_cancel: Optional[CancelCb] = None) -> list[dict]:
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise DriveError("There is nothing to upload.")
    total = sum(f.stat().st_size for f in files) or 1
    done_base = 0
    results: list[dict] = []
    folder_cache: dict[str, str] = {}

    from .utils import mime_for

    for idx, f in enumerate(files, 1):
        if should_cancel and should_cancel():
            raise UploadCancelled()
        rel_parent = f.parent.relative_to(root) if root.is_dir() else Path(".")
        parent_id = folder_id
        if str(rel_parent) != ".":
            key = str(rel_parent)
            if key not in folder_cache:
                folder_cache[key] = await drive.ensure_path(folder_id, key)
            parent_id = folder_cache[key]

        offset = done_base
        size_i = f.stat().st_size

        async def _cb(done: float, _total: float, _off=offset) -> None:
            if progress:
                await progress(_off + done, total)

        if report:
            await report(f.name, idx, len(files))
        meta = await drive.upload_file(f, parent_id, mime=mime_for(f.name),
                                       progress=_cb, should_cancel=should_cancel)
        done_base += size_i
        results.append(meta)
        if progress:
            await progress(done_base, total)
    return results
