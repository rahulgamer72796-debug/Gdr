"""Async SQLite storage — users, Google tokens, tasks, counters."""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

import aiosqlite

from .config import settings
from .logger import log

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    drive_mode  TEXT DEFAULT 'none',     -- none | oauth | sa
    folder_id   TEXT DEFAULT '',
    folder_name TEXT DEFAULT 'My Drive',
    as_doc      INTEGER DEFAULT 1,
    thumb       INTEGER DEFAULT 1,
    quality     TEXT DEFAULT 'best',
    cleanup     INTEGER DEFAULT 1,
    banned      INTEGER DEFAULT 0,
    created_at  REAL
);
CREATE TABLE IF NOT EXISTS tokens (
    user_id       INTEGER PRIMARY KEY,
    email         TEXT,
    access_token  TEXT,
    refresh_token TEXT,
    expires_at    REAL
);
CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER,
    mode         TEXT,                  -- mirror | leech
    source       TEXT,
    name         TEXT,
    size         INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'queued', -- queued running done failed cancelled
    phase        TEXT DEFAULT '',
    dest         TEXT DEFAULT '',
    cloud_id     TEXT DEFAULT '',
    error        TEXT DEFAULT '',
    created_at   REAL,
    finished_at  REAL
);
CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, value INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, created_at DESC);
"""

DEFAULT_USER = {
    "drive_mode": "none", "folder_id": "", "folder_name": "My Drive",
    "as_doc": 1, "thumb": 1, "quality": settings.default_quality, "cleanup": 1, "banned": 0,
}


class DB:
    def __init__(self) -> None:
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(settings.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        log.info("Database ready → %s", settings.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("DB not connected")
        return self._db

    # ── users ──────────────────────────────────────────────────────────────
    async def get_user(self, user_id: int, username: str = "", first_name: str = "") -> dict:
        async with self._lock:
            cur = await self.db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            if row is None:
                await self.db.execute(
                    "INSERT INTO users (user_id, username, first_name, created_at, quality) "
                    "VALUES (?,?,?,?,?)",
                    (user_id, username, first_name, time.time(), settings.default_quality),
                )
                await self.db.commit()
                cur = await self.db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
                row = await cur.fetchone()
            elif username and row["username"] != username:
                await self.db.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                                      (username, first_name, user_id))
                await self.db.commit()
        user = dict(row)
        if user_id == settings.owner_id:
            user["drive_mode"] = user["drive_mode"] or "none"
        return user

    async def update_user(self, user_id: int, **fields: Any) -> None:
        if not fields:
            return
        keys = ", ".join(f"{k}=?" for k in fields)
        async with self._lock:
            await self.db.execute(f"UPDATE users SET {keys} WHERE user_id=?",
                                  (*fields.values(), user_id))
            await self.db.commit()

    async def all_users(self) -> list[dict]:
        async with self._lock:
            cur = await self.db.execute("SELECT user_id FROM users WHERE banned=0")
            return [dict(r) for r in await cur.fetchall()]

    # ── tokens ─────────────────────────────────────────────────────────────
    async def set_token(self, user_id: int, email: str, access: str, refresh: str, expires_at: float,
                        account: str = "oauth") -> None:
        async with self._lock:
            await self.db.execute(
                "INSERT INTO tokens (user_id,email,access_token,refresh_token,expires_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "email=excluded.email, access_token=excluded.access_token, "
                "refresh_token=COALESCE(NULLIF(excluded.refresh_token,''), tokens.refresh_token), "
                "expires_at=excluded.expires_at",
                (user_id, email, access, refresh, expires_at))
            await self.db.execute("UPDATE users SET drive_mode=? WHERE user_id=?", (account, user_id))
            await self.db.commit()

    async def get_token(self, user_id: int) -> Optional[dict]:
        async with self._lock:
            cur = await self.db.execute("SELECT * FROM tokens WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        return dict(row) if row else None

    async def clear_token(self, user_id: int) -> None:
        async with self._lock:
            await self.db.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))
            await self.db.execute("UPDATE users SET drive_mode='none' WHERE user_id=?", (user_id,))
            await self.db.commit()

    # ── tasks ──────────────────────────────────────────────────────────────
    async def new_task(self, user_id: int, mode: str, source: str) -> str:
        tid = uuid.uuid4().hex[:10]
        async with self._lock:
            await self.db.execute(
                "INSERT INTO tasks (id,user_id,mode,source,status,created_at) VALUES (?,?,?,?,?,?)",
                (tid, user_id, mode, source, "queued", time.time()))
            await self.db.commit()
            await self._bump("tasks_started")
        return tid

    async def update_task(self, tid: str, **fields: Any) -> None:
        if not fields:
            return
        keys = ", ".join(f"{k}=?" for k in fields)
        async with self._lock:
            await self.db.execute(f"UPDATE tasks SET {keys} WHERE id=?", (*fields.values(), tid))
            await self.db.commit()

    async def finish_task(self, tid: str, status: str, error: str = "") -> None:
        async with self._lock:
            await self.db.execute(
                "UPDATE tasks SET status=?, error=?, finished_at=? WHERE id=?",
                (status, error[:400], time.time(), tid))
            await self.db.commit()
            if status == "done":
                await self._bump("tasks_done")
            elif status == "failed":
                await self._bump("tasks_failed")
            elif status == "cancelled":
                await self._bump("tasks_cancelled")

    async def recent_tasks(self, user_id: int, limit: int = 10) -> list[dict]:
        async with self._lock:
            cur = await self.db.execute(
                "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit))
            return [dict(r) for r in await cur.fetchall()]

    async def running_tasks(self) -> list[dict]:
        async with self._lock:
            cur = await self.db.execute(
                "SELECT * FROM tasks WHERE status IN ('queued','running') ORDER BY created_at")
            return [dict(r) for r in await cur.fetchall()]

    # ── counters ───────────────────────────────────────────────────────────
    async def _bump(self, key: str, n: int = 1) -> None:
        await self.db.execute(
            "INSERT INTO counters (key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = value + ?", (key, n, n))
        await self.db.commit()

    async def stats(self) -> dict:
        """Everything the admin panel shows — one round-trip, no N+1 queries."""
        async with self._lock:
            out: dict = {}
            for key in ("tasks_started", "tasks_done", "tasks_failed",
                        "tasks_cancelled", "bytes"):
                cur = await self.db.execute("SELECT value FROM counters WHERE key=?", (key,))
                row = await cur.fetchone()
                out[key] = row["value"] if row else 0

            day_ago = time.time() - 86400
            queries = {
                "users": "SELECT COUNT(*) c FROM users",
                "users_today": "SELECT COUNT(*) c FROM users WHERE created_at >= ?",
                "banned": "SELECT COUNT(*) c FROM users WHERE banned=1",
                "oauth_users": "SELECT COUNT(*) c FROM users WHERE drive_mode='oauth'",
                "sa_users": "SELECT COUNT(*) c FROM users WHERE drive_mode='sa'",
                "tasks_today": "SELECT COUNT(*) c FROM tasks WHERE created_at >= ?",
                "queued_now": "SELECT COUNT(*) c FROM tasks WHERE status IN ('queued','running')",
                "bytes_today": "SELECT COALESCE(SUM(size),0) c FROM tasks "
                               "WHERE status='done' AND finished_at >= ?",
            }
            for name, sql in queries.items():
                args = (day_ago,) if "?" in sql else ()
                cur = await self.db.execute(sql, args)
                out[name] = (await cur.fetchone())["c"]

            cur = await self.db.execute(
                "SELECT COALESCE(AVG(finished_at - created_at),0) c FROM tasks "
                "WHERE status='done' AND finished_at IS NOT NULL")
            out["avg_task_seconds"] = int((await cur.fetchone())["c"] or 0)
        return out

    async def user_stats(self, user_id: int) -> dict:
        """Per-user numbers: tasks, bytes, last task, success rate."""
        async with self._lock:
            cur = await self.db.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(size),0) b, MAX(finished_at) last "
                "FROM tasks WHERE user_id=? AND status='done'", (user_id,))
            row = await cur.fetchone()
            done, total_bytes, last = row["c"], row["b"], row["last"]
            cur = await self.db.execute(
                "SELECT COUNT(*) c FROM tasks WHERE user_id=?", (user_id,))
            total = (await cur.fetchone())["c"]
        return {"tasks_done": done, "bytes": total_bytes, "last_task": last,
                "tasks_total": total,
                "success_rate": round(done / total * 100, 1) if total else 0.0}

    async def add_bytes(self, n: int) -> None:
        if n > 0:
            await self._bump("bytes", n)


db = DB()
