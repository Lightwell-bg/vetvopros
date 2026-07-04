"""Неизвестные команды — после всех остальных роутеров."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

router = Router(name="fallback")


@router.message(F.text.startswith("/"), StateFilter(None))
async def unknown_command(message: Message) -> None:
    await message.answer("Команда не распознана. Справка: /help")
