"""Business logic facades."""

from vetvopros.services.answer_service import VetAnswerService
from vetvopros.services.billing_service import SqlBillingService
from vetvopros.services.llm_client import OpenAiCompatibleLlm
from vetvopros.services.llm_service import LlmError, LlmService
from vetvopros.services.protocols import (
    AnswerResult,
    AnswerService,
    BillingService,
    CabinetSnapshot,
    LlmClient,
    RagSearchService,
)
from vetvopros.services.rag_service import ChunkHit, RagService, default_embedder

__all__ = [
    "AnswerResult",
    "AnswerService",
    "BillingService",
    "CabinetSnapshot",
    "ChunkHit",
    "LlmClient",
    "LlmError",
    "LlmService",
    "VetAnswerService",
    "OpenAiCompatibleLlm",
    "RagSearchService",
    "RagService",
    "SqlBillingService",
    "default_embedder",
]
