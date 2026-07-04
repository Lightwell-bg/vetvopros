"""Кастомные фильтры aiogram (доступ к BotDeps через middleware)."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from vetvopros.bot.deps import BotDeps


class SpecialistReplyFilter(BaseFilter):
    """Входящее сообщение — ответ специалиста (reply) на наше bridge-сообщение."""

    async def __call__(self, message: Message, deps: BotDeps) -> bool:
        if message.reply_to_message is None or message.from_user is None:
            return False
        ids = deps.specialist_registry.all_resolved_ids()
        return message.from_user.id in ids


class SpecialistIdentityFilter(BaseFilter):
    """Отправитель — аккаунт из списка специалистов (по id из конфига / resolve username)."""

    async def __call__(self, message: Message, deps: BotDeps) -> bool:
        if message.from_user is None:
            return False
        return message.from_user.id in deps.specialist_registry.all_resolved_ids()


class ExcludeSpecialistUsersFilter(BaseFilter):
    """Исключить аккаунты специалистов из сценариев пациента (ИИ, анализы)."""

    async def __call__(self, message: Message, deps: BotDeps) -> bool:
        if message.from_user is None:
            return True
        return message.from_user.id not in deps.specialist_registry.all_resolved_ids()
