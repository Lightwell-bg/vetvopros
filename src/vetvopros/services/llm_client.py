"""Backward-compatible name for the OpenAI-compatible chat client."""

from __future__ import annotations

from vetvopros.services.llm_service import LlmError, LlmService

OpenAiCompatibleLlm = LlmService

__all__ = ["LlmError", "OpenAiCompatibleLlm"]
