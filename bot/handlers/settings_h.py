"""User settings handlers (kept separate so `settings` module name stays clean)."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

router = Router(name="settings")

# All settings toggles live in callbacks.py (set:*). This router exists so the
# package structure mirrors the menu; add per-user defaults here if needed.


@router.callback_query(F.data == "settings:noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()
