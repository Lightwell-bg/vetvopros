"""DB-related constants; must stay in sync with [rag] embedding_dimensions in config.ini."""

# Used by SQLAlchemy Vector column and documented alongside Alembic vector(N).
EMBEDDING_DIMENSIONS: int = 1536

# Значения `documents.status` (06_admin_panel.md).
DOCUMENT_STATUS_DRAFT: str = "draft"
DOCUMENT_STATUS_PUBLISHED: str = "published"
DOCUMENT_STATUS_ARCHIVED: str = "archived"

DOCUMENT_STATUSES: tuple[str, ...] = (
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_PUBLISHED,
    DOCUMENT_STATUS_ARCHIVED,
)
