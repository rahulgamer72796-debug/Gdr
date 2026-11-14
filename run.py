#!/usr/bin/env python3
"""MirrorX launcher — `python run.py` (or `python run.py --check` for a dry run)."""
from __future__ import annotations

import asyncio
import sys


def main() -> None:
    if any(a in ("-h", "--help") for a in sys.argv):
        print(__doc__)
        print("Commands:\n  python run.py          start the bot\n"
              "  python run.py --check  validate configuration and files")
        return

    from bot.config import settings
    from bot.logger import log

    problems = settings.validate()
    if "--check" in sys.argv:
        log.info("Config check → %s", "OK ✔" if not problems else "problems found")
        for p in problems:
            log.warning("  • %s", p)
        log.info("Token        : %s", settings.masked_token)
        log.info("Drive (OAuth): %s", "enabled" if settings.oauth_enabled else "not configured")
        log.info("Drive (SA)   : %s", "enabled" if settings.sa_path else "not configured")
        log.info("Download dir : %s", settings.download_dir)
        return

    if problems and not settings.bot_token:
        print("\n".join(["✖ Cannot start:"] + [f"  • {p}" for p in problems]))
        raise SystemExit(1)

    from bot.main import start
    try:
        asyncio.run(start())
    except (KeyboardInterrupt, SystemExit):
        log.info("Stop requested — bye 👋")


if __name__ == "__main__":
    main()
