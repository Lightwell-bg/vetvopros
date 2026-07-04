"""Разбиение markdown на чанки по параграфам с перекрытием (04_rag_design.md)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    """Один фрагмент для эмбеддинга и записи в document_chunks."""

    content: str
    heading: str | None
    chunk_index: int


_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+(.+)$")


def _normalize_markdown(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t


def _hard_split(text: str, size: int, overlap: int) -> list[str]:
    if size <= 0:
        return [text] if text else []
    out: list[str] = []
    step = max(1, size - overlap)
    i = 0
    n = len(text)
    while i < n:
        piece = text[i : i + size]
        if piece.strip():
            out.append(piece.strip())
        i += step
    return out or ([] if not text.strip() else [text.strip()])


def _paragraph_blocks(normalized: str) -> list[str]:
    parts = re.split(r"\n\s*\n", normalized)
    return [p.strip() for p in parts if p.strip()]


def _last_heading_in_chunk(text: str) -> str | None:
    last: str | None = None
    for line in text.split("\n"):
        m = _HEADING_LINE_RE.match(line.strip())
        if m:
            last = m.group(1).strip()
    return last


def chunk_markdown(
    body_markdown: str,
    *,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> list[TextChunk]:
    """
    Склейка мелких абзацев до целевого размера; крупные абзацы режутся окнами с перекрытием.
    Поле `document_slug` в chunk meta задаётся в `ingest.py`.
    """
    normalized = _normalize_markdown(body_markdown)
    if not normalized:
        return []

    size = max(200, chunk_size_chars)
    overlap = max(0, min(chunk_overlap_chars, size // 2))

    merged: list[str] = []
    buf = ""

    for block in _paragraph_blocks(normalized):
        candidate = f"{buf}\n\n{block}" if buf else block
        if len(candidate) <= size:
            buf = candidate
            continue
        if buf:
            merged.append(buf)
        if len(block) > size:
            merged.extend(_hard_split(block, size, overlap))
            buf = ""
        else:
            buf = block

    if buf:
        merged.append(buf)

    if overlap > 0 and len(merged) > 1:
        overlaid: list[str] = []
        for i, seg in enumerate(merged):
            if i == 0:
                overlaid.append(seg)
                continue
            prev = overlaid[-1]
            tail = prev[-overlap:] if len(prev) >= overlap else prev
            overlaid.append(f"{tail}\n{seg}".strip())
        merged = overlaid

    pieces: list[tuple[str, str | None]] = []
    for raw in merged:
        content = raw.strip()
        if not content:
            continue
        pieces.append((content, _last_heading_in_chunk(content)))

    return [TextChunk(content=c, heading=h, chunk_index=i) for i, (c, h) in enumerate(pieces)]


def chunk_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
