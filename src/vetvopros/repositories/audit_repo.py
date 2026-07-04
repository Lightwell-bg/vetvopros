"""Добавление и выборка записей audit_log."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.db.models import AuditLog
from vetvopros.db.session import session_scope


class AuditRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def append(
        self,
        *,
        user_id: uuid.UUID | None,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        with session_scope(self._factory) as s:
            row = AuditLog(user_id=user_id, event_type=event_type, details=details or {})
            s.add(row)
            s.flush()
            rid = row.id
        with session_scope(self._factory) as s:
            out = s.get(AuditLog, rid)
            assert out is not None
            return out

    def list_by_user(self, user_id: uuid.UUID, *, limit: int = 50) -> list[AuditLog]:
        with session_scope(self._factory) as s:
            q = (
                select(AuditLog)
                .where(AuditLog.user_id == user_id)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
            return list(s.scalars(q).all())

    def list_by_event_type(self, event_type: str, *, limit: int = 50) -> list[AuditLog]:
        with session_scope(self._factory) as s:
            q = (
                select(AuditLog)
                .where(AuditLog.event_type == event_type)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
            )
            return list(s.scalars(q).all())

    def list_recent(self, *, limit: int = 100, event_type: str | None = None) -> list[AuditLog]:
        with session_scope(self._factory) as s:
            q = select(AuditLog).order_by(AuditLog.created_at.desc())
            if event_type:
                q = q.where(AuditLog.event_type == event_type)
            q = q.limit(limit)
            return list(s.scalars(q).all())
