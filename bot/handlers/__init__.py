"""Handlers package."""
from aiogram import Router

from . import admin, callbacks, commands, files, settings_h, upload


def build_router() -> Router:
    root = Router(name="root")
    # order matters: commands → admin → callbacks → settings → files → upload (catch-all)
    root.include_router(commands.router)
    root.include_router(admin.router)
    root.include_router(settings_h.router)
    root.include_router(files.router)
    root.include_router(callbacks.router)
    root.include_router(upload.router)
    return root
