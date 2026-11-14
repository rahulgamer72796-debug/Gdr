"""Tiny logging setup with pretty colours."""
from __future__ import annotations

import logging
import sys


class _Fmt(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m", "INFO": "\033[32m", "WARNING": "\033[33m",
        "ERROR": "\033[31m", "CRITICAL": "\033[41m",
    }

    def format(self, record: logging.LogRecord) -> str:
        if sys.stderr.isatty():
            c = self.COLORS.get(record.levelname, "")
            record.levelname = f"{c}{record.levelname:<5}\033[0m"
        return super().format(record)


def _make() -> logging.Logger:
    from .config import settings  # local import keeps `.env` load order simple

    lg = logging.getLogger("mirrorx")
    if lg.handlers:
        return lg
    lg.setLevel(getattr(logging, settings.log_level, logging.INFO))
    h = logging.StreamHandler()
    h.setFormatter(_Fmt("%(asctime)s │ %(levelname)s │ %(name)s │ %(message)s", "%H:%M:%S"))
    lg.addHandler(h)
    lg.propagate = False
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    return lg


log = _make()
