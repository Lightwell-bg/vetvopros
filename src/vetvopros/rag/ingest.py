"""Полная переиндексация одного документа: только `published` получают векторы."""

from __future__ import annotations

import logging
import uuid

from vetvopros.db.constants import DOCUMENT_STATUS_PUBLISHED
from vetvopros.rag.chunking import chunk_content_hash, chunk_markdown
from vetvopros.rag.embeddings import EmbeddingProvider, EmbeddingRequestError
from vetvopros.repositories.chunk_repo import ChunkRepository
from vetvopros.repositories.document_repo import DocumentRepository

log = logging.getLogger(__name__)


def ingest_document(
    *,
    document_id: uuid.UUID,
    documents: DocumentRepository,
    chunks: ChunkRepository,
    embedder: EmbeddingProvider,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    embedding_model: str,
) -> None:
    """
    Черновик / снятие с публикации: удалить все чанки.
    Опубликованный: пересчитать чанки и эмбеддинги, затем заменить строки в БД.
    При ошибке эмбеддинга старые чанки сохраняются (сначала запрос к API, потом delete).
    """
    doc = documents.get_by_id(document_id)
    if doc is None:
        log.warning("ingest_document_missing", extra={"structured": {"document_id": str(document_id)}})
        return

    if doc.status != DOCUMENT_STATUS_PUBLISHED:
        chunks.delete_for_document(document_id)
        log.info(
            "ingest_document_skipped_not_published",
            extra={"structured": {"document_id": str(document_id), "status": doc.status}},
        )
        return

    parts = chunk_markdown(
        doc.body_markdown,
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )
    texts = [p.content for p in parts]
    if not texts:
        log.warning(
            "ingest_document_empty_after_chunking",
            extra={
                "structured": {
                    "document_id": str(document_id),
                    "slug": doc.slug,
                    "body_chars": len(doc.body_markdown or ""),
                },
            },
        )
        chunks.delete_for_document(document_id)
        return

    try:
        vectors = embedder.embed_texts(texts)
    except EmbeddingRequestError:
        log.exception(
            "ingest_document_embedding_failed",
            extra={"structured": {"document_id": str(document_id), "slug": doc.slug}},
        )
        raise

    if len(vectors) != len(parts):
        msg = f"embedding count {len(vectors)} != chunks {len(parts)}"
        raise EmbeddingRequestError(msg)

    chunks.delete_for_document(document_id)
    for tc, emb in zip(parts, vectors, strict=True):
        meta = {
            "heading": tc.heading,
            "document_slug": doc.slug,
            "chunk_index": tc.chunk_index,
            "content_hash": chunk_content_hash(tc.content),
            "embedding_model": embedding_model,
        }
        chunks.insert_chunk(
            document_id=document_id,
            chunk_index=tc.chunk_index,
            content=tc.content,
            embedding=emb,
            meta=meta,
        )
