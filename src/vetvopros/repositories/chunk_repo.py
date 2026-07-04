"""Чанки документов и векторный поиск (cosine distance <=> )."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.db.constants import EMBEDDING_DIMENSIONS
from vetvopros.db.constants import DOCUMENT_STATUS_PUBLISHED
from vetvopros.db.models import Document, DocumentChunk
from vetvopros.db.session import session_scope


class ChunkRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def delete_for_document(self, document_id: uuid.UUID) -> None:
        with session_scope(self._factory) as s:
            s.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))

    def count_all(self) -> int:
        with session_scope(self._factory) as s:
            n = s.scalar(select(func.count()).select_from(DocumentChunk))
            return int(n or 0)

    def count_for_document(self, document_id: uuid.UUID) -> int:
        with session_scope(self._factory) as s:
            n = s.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.document_id == document_id),
            )
            return int(n or 0)

    def counts_for_documents(self, document_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Число чанков по каждому id; для id без строк — 0."""
        ids = list(document_ids)
        out: dict[uuid.UUID, int] = {i: 0 for i in ids}
        if not ids:
            return out
        with session_scope(self._factory) as s:
            rows = s.execute(
                select(DocumentChunk.document_id, func.count())
                .where(DocumentChunk.document_id.in_(ids))
                .group_by(DocumentChunk.document_id),
            ).all()
        for did, cnt in rows:
            out[did] = int(cnt)
        return out

    def insert_chunk(
        self,
        *,
        document_id: uuid.UUID,
        chunk_index: int,
        content: str,
        embedding: Sequence[float],
        meta: dict | None = None,
    ) -> DocumentChunk:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            msg = f"embedding length {len(embedding)} != {EMBEDDING_DIMENSIONS}"
            raise ValueError(msg)
        with session_scope(self._factory) as s:
            row = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk_index,
                content=content,
                embedding=list(embedding),
                chunk_meta=meta or {},
            )
            s.add(row)
            s.flush()
            chunk_id = row.id
        with session_scope(self._factory) as s:
            out = s.get(DocumentChunk, chunk_id)
            assert out is not None
            return out

    def list_for_document(self, document_id: uuid.UUID) -> list[DocumentChunk]:
        with session_scope(self._factory) as s:
            q = (
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index.asc())
            )
            return list(s.scalars(q).all())

    def search_similar(
        self,
        query_embedding: Sequence[float],
        *,
        limit: int = 5,
    ) -> list[tuple[DocumentChunk, float]]:
        """Возвращает (чанк, cosine distance); меньше — ближе по смыслу."""
        if len(query_embedding) != EMBEDDING_DIMENSIONS:
            msg = f"embedding length {len(query_embedding)} != {EMBEDDING_DIMENSIONS}"
            raise ValueError(msg)
        qe = list(query_embedding)
        with session_scope(self._factory) as s:
            dist = DocumentChunk.embedding.cosine_distance(qe)
            stmt = (
                select(DocumentChunk, dist.label("distance"))
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.status == DOCUMENT_STATUS_PUBLISHED)
                .order_by(dist)
                .limit(limit)
            )
            rows = s.execute(stmt).all()
            out: list[tuple[DocumentChunk, float]] = []
            for row in rows:
                ch, distance = row[0], float(row[1])
                _ = ch.document.slug  # подгрузить связь до закрытия сессии
                out.append((ch, distance))
            return out
