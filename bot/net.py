"""Dedicated async HTTP client for Drive + downloads.

Important: `aiogram.Bot.session` is the *Telegram API session*, not an
`aiohttp.ClientSession` — reusing it for Drive/downloads is a classic bug.
Everything non-Telegram goes through `http` below.
"""
from __future__ import annotations

import asyncio

import aiohttp

from .logger import log

_http: aiohttp.ClientSession | None = None
_lock = asyncio.Lock()


async def get_http() -> aiohttp.ClientSession:
    global _http
    async with _lock:
        if _http is None or _http.closed:
            _http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=300),
                headers={"User-Agent": "MirrorX/1.0 (+https://t.me/PublicBotsHub)"},
                auto_decompress=True,
            )
            log.debug("HTTP client created")
    return _http


async def close_http() -> None:
    global _http
    if _http and not _http.closed:
        await _http.close()
        await asyncio.sleep(0.1)
    _http = None
