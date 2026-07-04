"""Фасад RAG: индексация и retrieve для AnswerService / админки."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from vetvopros.config.settings import Settings
from vetvopros.db.constants import DOCUMENT_STATUS_PUBLISHED
from vetvopros.rag.embeddings import EmbeddingClient, EmbeddingProvider, EmbeddingRequestError
from vetvopros.rag.ingest import ingest_document
from vetvopros.rag.search import cosine_distance_to_similarity
from vetvopros.repositories.chunk_repo import ChunkRepository
from vetvopros.repositories.document_repo import DocumentRepository

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_slug: str
    chunk_index: int
    content: str
    score: float


class RagService:
    """
    Публичный API для agent_07 (индексация) и agent_06/AnswerService (поиск).
    Ошибки эмбеддинга при retrieve не роняют процесс — пустой список и лог.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        documents: DocumentRepository,
        chunks: ChunkRepository,
        embedder: EmbeddingProvider,
    ) -> None:
        self._settings = settings
        self._documents = documents
        self._chunks = chunks
        self._embedder = embedder

    def retrieve(self, query: str, *, top_k: int | None = None) -> list[ChunkHit]:
        q = (query or "").strip()
        if not q:
            return []
        k = int(top_k if top_k is not None else self._settings.rag.top_k)
        k = max(1, k)
        try:
            query_vec = self._embedder.embed_texts([q])[0]
        except EmbeddingRequestError:
            log.warning("rag_retrieve_embedding_failed", exc_info=True)
            return []

        raw = self._chunks.search_similar(query_vec, limit=k)
        threshold = float(self._settings.rag.min_similarity)
        max_ctx = int(self._settings.rag.max_context_chunks)
        hits: list[ChunkHit] = []
        best_score: float | None = None
        for chunk, dist in raw:
            score = cosine_distance_to_similarity(dist)
            best_score = score if best_score is None else max(best_score, score)
            if score < threshold:
                continue
            hits.append(
                ChunkHit(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_slug=chunk.document.slug,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    score=score,
                )
            )
            if len(hits) >= max_ctx:
                break
        if not hits and raw:
            log.info(
                "rag_no_hits_above_threshold",
                extra={
                    "structured": {
                        "threshold": threshold,
                        "top_k": k,
                        "best_similarity": best_score,
                    }
                },
            )
        return hits

    def message_metadata(self, hits: list[ChunkHit]) -> dict[str, Any]:
        """Поля для `messages.metadata` / аудита (04_rag_design.md)."""
        model = self._settings.rag.embedding_model
        thr = float(self._settings.rag.min_similarity)
        if not hits:
            return {
                "chunk_ids": [],
                "similarities": [],
                "document_slugs": [],
                "model": model,
                "rag_threshold_used": thr,
            }
        return {
            "chunk_ids": [str(h.chunk_id) for h in hits],
            "similarities": [h.score for h in hits],
            "document_slugs": [h.document_slug for h in hits],
            "model": model,
            "rag_threshold_used": thr,
        }

    def search(self, query: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
        """Совместимость с протоколом RagSearchService."""
        return [self._hit_as_dict(h) for h in self.retrieve(query, top_k=top_k)]

    @staticmethod
    def _hit_as_dict(h: ChunkHit) -> dict[str, Any]:
        return {
            "chunk_id": str(h.chunk_id),
            "document_id": str(h.document_id),
            "document_slug": h.document_slug,
            "chunk_index": h.chunk_index,
            "content": h.content,
            "score": h.score,
        }

    def reindex_document(self, document_id: uuid.UUID) -> None:
        ingest_document(
            document_id=document_id,
            documents=self._documents,
            chunks=self._chunks,
            embedder=self._embedder,
            chunk_size_chars=self._settings.rag.chunk_size_chars,
            chunk_overlap_chars=self._settings.rag.chunk_overlap_chars,
            embedding_model=self._settings.rag.embedding_model,
        )

    def reindex_all_published(self, *, page_size: int = 100) -> tuple[int, int]:
        """Переиндексирует все опубликованные документы. Возвращает (успехи, ошибки)."""
        ok = 0
        failed = 0
        offset = 0
        ps = max(1, page_size)
        while True:
            batch = self._documents.list_by_status(
                DOCUMENT_STATUS_PUBLISHED,
                limit=ps,
                offset=offset,
            )
            if not batch:
                break
            for doc in batch:
                try:
                    self.reindex_document(doc.id)
                    ok += 1
                except EmbeddingRequestError:
                    failed += 1
                    log.exception(
                        "rag_reindex_document_failed",
                        extra={"structured": {"document_id": str(doc.id), "slug": doc.slug}},
                    )
            offset += ps
        return ok, failed


def default_embedder(settings: Settings) -> EmbeddingClient:
    return EmbeddingClient(settings)
