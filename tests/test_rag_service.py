"""Юнит-тесты RagService (моки эмбеддингов и репозитория)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pathlib import Path

from vetvopros.config.settings import IniBilling, IniFeatures, IniLlm, IniPaths, IniRag, Settings
from vetvopros.rag.embeddings import EmbeddingRequestError
from vetvopros.services.rag_service import ChunkHit, RagService


def _minimal_settings(**rag_overrides: object) -> Settings:
    rag_kw = {
        "chunk_size_chars": 800,
        "chunk_overlap_chars": 80,
        "top_k": 5,
        "min_similarity": 0.5,
        "max_context_chunks": 3,
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
    }
    rag_kw.update(rag_overrides)
    return Settings(
        app_name="t",
        environment="development",
        log_level="INFO",
        paths=IniPaths(
            texts_dir="texts",
            prompts_dir="prompts",
            system_prompt_file="p/s.txt",
            prompt_analysis_suggestions="p/a.txt",
            prompt_analysis_interpretation="p/i.txt",
        ),
        database_pool_size=5,
        telegram_polling_timeout=60,
        rag=IniRag(**rag_kw),
        llm=IniLlm(chat_model="x", request_timeout_seconds=30, max_output_tokens=256),
        features=IniFeatures(
            enable_analyses_flow=True,
            enable_specialist_menu=True,
            auto_index_on_publish=True,
        ),
        billing=IniBilling(
            free_answers_per_user=10,
            free_specialist_messages_per_user=3,
            specialist_message_cost=1,
        ),
        database_url="postgresql:///",
        telegram_bot_token="",
        llm_api_key="k",
        llm_base_url=None,
        admin_session_secret="",
        admin_username="admin",
        admin_password="",
        admin_uvicorn_host="0.0.0.0",
        admin_uvicorn_port=8000,
        admin_uvicorn_reload=False,
        payment_provider="stub",
        payment_webhook_secret="",
        config_ini_path=Path("."),
    )


def test_retrieve_empty_query() -> None:
    svc = RagService(
        _minimal_settings(),
        documents=MagicMock(),
        chunks=MagicMock(),
        embedder=MagicMock(),
    )
    assert svc.retrieve("") == []
    assert svc.retrieve("   ") == []


def test_retrieve_embedding_error_returns_empty() -> None:
    emb = MagicMock()
    emb.embed_texts.side_effect = EmbeddingRequestError("down")
    svc = RagService(_minimal_settings(), documents=MagicMock(), chunks=MagicMock(), embedder=emb)
    assert svc.retrieve("вопрос") == []


def test_retrieve_respects_threshold_and_max_context() -> None:
    doc_id = uuid.uuid4()
    doc = SimpleNamespace(slug="s")
    ch_ok = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=doc_id,
        chunk_index=0,
        content="c1",
        document=doc,
    )
    ch_bad = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=doc_id,
        chunk_index=1,
        content="c2",
        document=doc,
    )

    chunks = MagicMock()
    # distances: similarity = 1 - dist -> 0.9 and 0.2 при min_similarity 0.5
    chunks.search_similar.return_value = [(ch_ok, 0.1), (ch_bad, 0.8)]

    emb = MagicMock()
    emb.embed_texts.return_value = [[0.1] * 1536]

    svc = RagService(
        _minimal_settings(min_similarity=0.5, max_context_chunks=2, top_k=5),
        documents=MagicMock(),
        chunks=chunks,
        embedder=emb,
    )
    hits = svc.retrieve("q")
    assert len(hits) == 1
    assert hits[0].content == "c1"
    assert hits[0].score == pytest.approx(0.9)


def test_message_metadata_shape() -> None:
    svc = RagService(_minimal_settings(min_similarity=0.72), documents=MagicMock(), chunks=MagicMock(), embedder=MagicMock())
    hid = uuid.uuid4()
    hits = [
        ChunkHit(
            chunk_id=hid,
            document_id=uuid.uuid4(),
            document_slug="faq",
            chunk_index=0,
            content="x",
            score=0.91,
        )
    ]
    meta = svc.message_metadata(hits)
    assert meta["rag_threshold_used"] == pytest.approx(0.72)
    assert meta["model"] == "text-embedding-3-small"
    assert meta["chunk_ids"] == [str(hid)]
    assert meta["similarities"] == [pytest.approx(0.91)]
    assert meta["document_slugs"] == ["faq"]
