"""Преобразование расстояния pgvector в similarity и отбор по порогу."""

from __future__ import annotations


def cosine_distance_to_similarity(distance: float) -> float:
    """Для cosine distance из pgvector: similarity = 1 - distance (04_rag_design.md)."""
    return 1.0 - float(distance)


def filter_by_similarity(
    scores: list[float],
    *,
    min_similarity: float,
) -> list[bool]:
    return [s >= min_similarity for s in scores]
