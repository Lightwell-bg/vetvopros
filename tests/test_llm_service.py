"""Юнит-тесты LlmService (мок httpx, без реального API)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from vetvopros.config.settings import IniBilling, IniFeatures, IniLlm, IniPaths, IniRag, Settings
from vetvopros.services.llm_service import LlmError, LlmService


def _settings(**llm_overrides: object) -> Settings:
    llm_kw: dict = {
        "chat_model": "test-model",
        "request_timeout_seconds": 30,
        "max_output_tokens": 256,
        "max_retries": 2,
        "retry_backoff_seconds": 0.01,
        "reduce_log_detail": True,
    }
    llm_kw.update(llm_overrides)
    return Settings(
        app_name="t",
        environment="development",
        log_level="INFO",
        paths=IniPaths(
            texts_dir="texts",
            prompts_dir="prompts",
            system_prompt_file="prompts/system_prompt.md",
            prompt_analysis_suggestions="prompts/analysis_suggestions.md",
            prompt_analysis_interpretation="prompts/analysis_interpretation.md",
        ),
        database_pool_size=5,
        telegram_polling_timeout=60,
        rag=IniRag(
            chunk_size_chars=800,
            chunk_overlap_chars=80,
            top_k=5,
            min_similarity=0.5,
            max_context_chunks=3,
            embedding_model="text-embedding-3-small",
            embedding_dimensions=1536,
        ),
        llm=IniLlm(**llm_kw),
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
        llm_api_key="test-key",
        llm_base_url="https://example.test/v1",
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


def _mock_client_flow(responses: list[httpx.Response]) -> MagicMock:
    """Return MagicMock for httpx.Client context manager; post() consumes responses in order."""
    posts = iter(responses)

    def _post(*_a, **_kw):
        return next(posts)

    mock_client = MagicMock()
    mock_client.post.side_effect = _post
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = None
    mock_cls = MagicMock(return_value=mock_cm)
    return mock_cls


def test_complete_success_parses_choice() -> None:
    data = {"choices": [{"message": {"content": "  Answer  "}}]}
    ok = httpx.Response(200, json=data)
    mock_cls = _mock_client_flow([ok])
    svc = LlmService(_settings())
    with patch("vetvopros.services.llm_service.httpx.Client", mock_cls):
        out = svc.complete([{"role": "user", "content": "hi"}])
    assert out == "Answer"
    mock_cls.return_value.__enter__.return_value.post.assert_called_once()


def test_complete_with_system_builds_messages() -> None:
    data = {"choices": [{"message": {"content": "ok"}}]}
    ok = httpx.Response(200, json=data)
    mock_cls = _mock_client_flow([ok])
    mock_post = MagicMock(return_value=ok)
    mock_client = MagicMock()
    mock_client.post = mock_post
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = None
    with patch("vetvopros.services.llm_service.httpx.Client", return_value=mock_cm):
        svc = LlmService(_settings())
        svc.complete_with_system("SYS", "USER")
    call_kw = mock_post.call_args.kwargs
    payload = call_kw["json"]
    assert payload["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert payload["model"] == "test-model"


def test_retry_on_429_then_success() -> None:
    r429 = httpx.Response(429, headers={"Retry-After": "0"})
    r200 = httpx.Response(200, json={"choices": [{"message": {"content": "after"}}]})
    mock_cls = _mock_client_flow([r429, r200])
    svc = LlmService(_settings())
    with (
        patch("vetvopros.services.llm_service.httpx.Client", mock_cls),
        patch("vetvopros.services.llm_service.time.sleep") as sl,
    ):
        out = svc.complete([{"role": "user", "content": "x"}])
    assert out == "after"
    assert mock_cls.return_value.__enter__.return_value.post.call_count == 2
    assert sl.called


def test_llm_error_on_401_no_key_in_message() -> None:
    r401 = httpx.Response(401, json={"error": {"message": "invalid_api_key"}})
    mock_cls = _mock_client_flow([r401])
    svc = LlmService(_settings(max_retries=0))
    with patch("vetvopros.services.llm_service.httpx.Client", mock_cls):
        with pytest.raises(LlmError) as ei:
            svc.complete([{"role": "user", "content": "x"}])
    assert "test-key" not in str(ei.value).lower()
    assert "unauthorized" in str(ei.value).lower()


def test_timeout_retries_then_llm_error() -> None:
    mock_cls = MagicMock()

    def _post(*_a, **_kw):
        raise httpx.TimeoutException("timeout")

    mock_client = MagicMock()
    mock_client.post.side_effect = _post
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = None
    mock_cls.return_value = mock_cm
    svc = LlmService(_settings(max_retries=1, retry_backoff_seconds=0.001))
    with (
        patch("vetvopros.services.llm_service.httpx.Client", mock_cls),
        patch("vetvopros.services.llm_service.time.sleep"),
    ):
        with pytest.raises(LlmError) as ei:
            svc.complete([{"role": "user", "content": "x"}])
    assert "retries" in str(ei.value).lower()
    assert mock_client.post.call_count == 2


def test_load_main_system_prompt_reads_file() -> None:
    svc = LlmService(_settings())
    text = svc.load_main_system_prompt()
    assert len(text) > 10
    lo = text.lower()
    assert "ветеринар" in lo or "ассистент" in lo or "справочн" in lo or "питомец" in lo
