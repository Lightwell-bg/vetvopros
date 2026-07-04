"""Разрешение Telegram user id специалиста (число в конфиге или @username через Bot.get_chat)."""

from __future__ import annotations

from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from vetvopros.config.specialists import SpecialistCard
from vetvopros.utils.logging import get_logger

log = get_logger(__name__)

_PLACEHOLDER_USERNAMES = frozenset(
    {
        "replace_me",
        "example",
        "username",
        "your_username",
        "none",
        "test",
        "xxx",
        "user",
        "me",
        "placeholder",
        "changeme",
    }
)


def _looks_like_placeholder_username(raw: str) -> bool:
    u = raw.strip().lstrip("@").lower()
    return not u or u in _PLACEHOLDER_USERNAMES


@dataclass
class SpecialistRegistry:
    cards: list[SpecialistCard]
    _id_by_key: dict[str, int] = field(default_factory=dict)

    def all_resolved_ids(self) -> frozenset[int]:
        return frozenset(self._id_by_key.values())

    async def telegram_id_for(self, bot: Bot, key: str) -> int | None:
        if key in self._id_by_key:
            return self._id_by_key[key]
        card = next((c for c in self.cards if c.key == key), None)
        if card is None:
            return None
        if card.telegram_user_id is not None and int(card.telegram_user_id) != 0:
            self._id_by_key[key] = int(card.telegram_user_id)
            return self._id_by_key[key]
        if card.telegram_username:
            un = card.telegram_username.lstrip("@").strip()
            if _looks_like_placeholder_username(un):
                log.warning(
                    "specialist_username_skipped_placeholder",
                    extra={"structured": {"specialist_key": key, "username": un}},
                )
                return None
            try:
                chat = await bot.get_chat(f"@{un}")
            except TelegramAPIError as e:
                log.warning(
                    "specialist_get_chat_failed",
                    extra={
                        "structured": {
                            "specialist_key": key,
                            "username": un,
                            "error": str(e),
                        }
                    },
                )
                return None
            self._id_by_key[key] = int(chat.id)
            return self._id_by_key[key]
        return None

    async def prime_all(self, bot: Bot) -> None:
        for c in self.cards:
            await self.telegram_id_for(bot, c.key)
