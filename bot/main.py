"""MirrorX — application entry point."""
from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, LinkPreviewOptions

from .config import settings
from .db import db
from .handlers import build_router
from .logger import log
from .net import close_http
from .services import logger_channel
from .services.tasks import manager
from .ui.emoji import emoji

VERSION = "1.0.0"

COMMANDS = [
    BotCommand(command="start", description="Main menu 🚀"),
    BotCommand(command="mirror", description="Mirror a link → Google Drive"),
    BotCommand(command="leech", description="Leech a link → Telegram"),
    BotCommand(command="login", description="Connect Google Drive (email)"),
    BotCommand(command="drive", description="Drive status & storage"),
    BotCommand(command="status", description="Active tasks"),
    BotCommand(command="cancel", description="Cancel a running task"),
    BotCommand(command="files", description="Browse Drive files"),
    BotCommand(command="settings", description="Your preferences"),
    BotCommand(command="help", description="Everything this bot can do"),
]


async def on_startup(bot: Bot) -> None:
    await db.connect()
    manager.setup(bot)
    await emoji.verify(bot)
    me = await bot.get_me()
    settings.bot_username = f"@{me.username}" if me.username else settings.bot_username
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.set_chat_menu_button()
    except Exception as e:  # noqa: BLE001
        log.debug("set_my_commands failed: %s", e)
    log.info("─" * 62)
    log.info("  %s v%s is online as @%s", settings.bot_name, VERSION, me.username)
    log.info("  premium emoji : %s", "ON ✔" if emoji.custom else "fallback (plain) mode")
    log.info("  email login   : %s", "enabled" if settings.oauth_enabled else "disabled")
    log.info("  service acct  : %s", "enabled" if settings.sa_path else "disabled")
    log.info("  workers       : %s concurrent", settings.max_concurrent)
    log.info("  log channel   : %s", logger_channel.status())
    log.info("─" * 62)
    logger_channel.setup(bot)
    try:
        await logger_channel.startup(VERSION)
    except Exception as e:  # noqa: BLE001
        log.debug("log-channel startup ping failed: %s", e)


async def on_shutdown(bot: Bot) -> None:
    log.info("Shutting down — cancelling tasks…")
    for task in manager.all_active():
        await manager.cancel(task.id)
    await db.close()
    await close_http()


async def start() -> None:
    session = AiohttpSession()
    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview=LinkPreviewOptions(is_disabled=True),
        ),
    )
    dp = Dispatcher()
    dp.include_router(build_router())
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    log.info("Starting %s…", settings.bot_name)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"],
                           drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(start())
