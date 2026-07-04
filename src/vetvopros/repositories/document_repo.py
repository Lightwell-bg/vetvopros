"""CRUD для документов базы знаний."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.db.models import Document
from vetvopros.db.session import session_scope

PUBLISHED_AT_UNCHANGED = object()


class DocumentRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def get_by_id(self, doc_id: uuid.UUID) -> Document | None:
        with session_scope(self._factory) as s:
            return s.get(Document, doc_id)

    def get_by_slug(self, slug: str) -> Document | None:
        with session_scope(self._factory) as s:
            return s.scalar(select(Document).where(Document.slug == slug))

    def list_by_status(self, status: str, *, limit: int = 100, offset: int = 0) -> list[Document]:
        with session_scope(self._factory) as s:
            q = (
                select(Document)
                .where(Document.status == status)
                .order_by(Document.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(s.scalars(q).all())

    def list_filtered(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Document]:
        with session_scope(self._factory) as s:
            q = select(Document).order_by(Document.updated_at.desc())
            if status:
                q = q.where(Document.status == status)
            if search and search.strip():
                term = f"%{search.strip()}%"
                q = q.where(
                    or_(
                        Document.title.ilike(term),
                        Document.slug.ilike(term),
                    )
                )
            q = q.limit(limit).offset(offset)
            return list(s.scalars(q).all())

    def count_by_status(self) -> dict[str, int]:
        with session_scope(self._factory) as s:
            rows = s.execute(select(Document.status, func.count()).group_by(Document.status)).all()
            return {str(st): int(n) for st, n in rows}

    def create(
        self,
        *,
        title: str,
        slug: str,
        body_markdown: str,
        status: str,
    ) -> Document:
        with session_scope(self._factory) as s:
            doc = Document(title=title, slug=slug, body_markdown=body_markdown, status=status)
            s.add(doc)
            s.flush()
            doc_id = doc.id
        with session_scope(self._factory) as s:
            out = s.get(Document, doc_id)
            assert out is not None
            return out

    def update(
        self,
        doc_id: uuid.UUID,
        *,
        title: str | None = None,
        body_markdown: str | None = None,
        status: str | None = None,
        slug: str | None = None,
        published_at: datetime | None | Any = PUBLISHED_AT_UNCHANGED,
    ) -> Document | None:
        with session_scope(self._factory) as s:
            doc = s.get(Document, doc_id)
            if doc is None:
                return None
            if title is not None:
                doc.title = title
            if body_markdown is not None:
                doc.body_markdown = body_markdown
            if status is not None:
                doc.status = status
            if slug is not None:
                doc.slug = slug
            if published_at is not PUBLISHED_AT_UNCHANGED:
                doc.published_at = published_at
        return self.get_by_id(doc_id)

    def delete(self, doc_id: uuid.UUID) -> bool:
        with session_scope(self._factory) as s:
            doc = s.get(Document, doc_id)
            if doc is None:
                return False
            s.delete(doc)
            return True
