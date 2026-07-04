"""Message history (sync)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.db.models import Message
from vetvopros.db.session import session_scope


class MessageRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def add_message(
        self,
        *,
        user_id: uuid.UUID,
        role: str,
        content: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        with session_scope(self._factory) as s:
            msg = Message(
                user_id=user_id,
                role=role,
                content=content,
                source=source,
                message_metadata=metadata or {},
            )
            s.add(msg)
            s.flush()
            return msg.id

    def list_for_user(self, user_id: uuid.UUID, *, limit: int = 50) -> list[Message]:
        with session_scope(self._factory) as s:
            q = (
                select(Message)
                .where(Message.user_id == user_id)
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            return list(s.scalars(q).all())
