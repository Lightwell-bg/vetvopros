"""RAG: чанкинг, эмбеддинги, индексация, поиск."""

from vetvopros.rag.chunking import chunk_content_hash, chunk_markdown
from vetvopros.rag.embeddings import EmbeddingClient, EmbeddingRequestError
from vetvopros.rag.ingest import ingest_document
from vetvopros.rag.search import cosine_distance_to_similarity, filter_by_similarity

__all__ = [
    "EmbeddingClient",
    "EmbeddingRequestError",
    "chunk_content_hash",
    "chunk_markdown",
    "cosine_distance_to_similarity",
    "filter_by_similarity",
    "ingest_document",
]
