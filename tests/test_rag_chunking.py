"""Юнит-тесты чанкинга markdown (без БД)."""

from __future__ import annotations

from vetvopros.rag.chunking import chunk_content_hash, chunk_markdown


def test_chunk_markdown_empty() -> None:
    assert chunk_markdown("", chunk_size_chars=500, chunk_overlap_chars=50) == []


def test_chunk_markdown_merges_short_paragraphs() -> None:
    body = "А.\n\nБ.\n\nВ."
    parts = chunk_markdown(body, chunk_size_chars=200, chunk_overlap_chars=20)
    assert len(parts) >= 1
    joined = " ".join(p.content for p in parts)
    assert "А" in joined and "Б" in joined


def test_chunk_markdown_heading_meta() -> None:
    body = "## Заголовок\n\nТекст под ним."
    parts = chunk_markdown(body, chunk_size_chars=500, chunk_overlap_chars=50)
    assert parts
    assert parts[0].heading == "Заголовок"


def test_chunk_content_hash_stable() -> None:
    h1 = chunk_content_hash("same")
    h2 = chunk_content_hash("same")
    h3 = chunk_content_hash("other")
    assert h1 == h2
    assert h1 != h3
