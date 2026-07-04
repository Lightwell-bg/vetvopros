"""Inject BotDeps into handler data."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from vetvopros.bot.deps import BotDeps


class DepsMiddleware(BaseMiddleware):
    def __init__(self, deps: BotDeps) -> None:
        super().__init__()
        self._deps = deps

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["deps"] = self._deps
        return await handler(event, data)
