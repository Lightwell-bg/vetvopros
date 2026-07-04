"""User persistence (sync)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.db.models import User, UserBalance
from vetvopros.db.session import session_scope


class UserRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def get_by_telegram_id(self, telegram_id: int) -> User | None:
        with session_scope(self._factory) as s:
            return s.scalar(select(User).where(User.telegram_id == telegram_id))

    def disclaimer_accepted(self, telegram_id: int) -> bool:
        user = self.get_by_telegram_id(telegram_id)
        return user is not None and user.disclaimer_accepted_at is not None

    def get_or_create(self, telegram_id: int, username: str | None) -> User:
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                user = User(telegram_id=telegram_id, username=username)
                s.add(user)
                s.flush()
                s.add(UserBalance(user_id=user.id))
            elif username and user.username != username:
                user.username = username
        with session_scope(self._factory) as s:
            out = s.scalar(select(User).where(User.telegram_id == telegram_id))
            assert out is not None
            return out

    def accept_disclaimer(self, telegram_id: int) -> None:
        now = datetime.now(UTC)
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                user = User(telegram_id=telegram_id, username=None)
                s.add(user)
                s.flush()
                s.add(UserBalance(user_id=user.id))
            user.disclaimer_accepted_at = now

    def clear_all_disclaimers(self) -> None:
        """Сброс принятия условий у всех пользователей (остановка/запуск процесса бота)."""
        with session_scope(self._factory) as s:
            s.execute(update(User).values(disclaimer_accepted_at=None))
