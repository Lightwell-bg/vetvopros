"""Юнит-тесты VetAnswerService: guardrails, billing_block, RAG+LLM в ask(), списание квоты."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vetvopros.config.settings import load_settings
from vetvopros.services.answer_service import VetAnswerService

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings():
    return load_settings(config_ini=str(_REPO_ROOT / "config.ini"))


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


def _service(
    settings,
    *,
    user_id: uuid.UUID,
    billing_can: bool = True,
    llm_text: str = "Краткий ориентир для обсуждения с врачом.",
) -> tuple[VetAnswerService, MagicMock, MagicMock, MagicMock, MagicMock]:
    user = SimpleNamespace(id=user_id)
    users = MagicMock()
    users.get_or_create.return_value = user
    billing = MagicMock()
    billing.can_answer.return_value = billing_can
    messages = MagicMock()
    messages.add_message.side_effect = [uuid.uuid4(), uuid.uuid4()]
    llm = MagicMock()
    llm.load_main_system_prompt.return_value = "system"
    llm.complete.return_value = llm_text
    messages.list_for_user.return_value = []
    rag = MagicMock()
    rag.retrieve.return_value = []
    rag.message_metadata.return_value = {}
    svc = VetAnswerService(settings, users, billing, messages, llm, rag)
    return svc, billing, messages, llm, rag


def test_ask_red_flag_no_llm_no_billing_consume(settings, user_id) -> None:
    svc, billing, _, llm, rag = _service(settings, user_id=user_id)
    r = svc.ask(9_001_001_001, "кот не может помочиться уже 6 часов")
    assert r.source == "guardrail"
    assert r.metadata.get("kind") == "red_flag"
    billing.check_and_consume_answer_credit.assert_not_called()
    llm.complete_with_system.assert_not_called()
    rag.retrieve.assert_not_called()


def test_ask_billing_block_no_llm_no_consume(settings, user_id) -> None:
    svc, billing, _, llm, rag = _service(settings, user_id=user_id, billing_can=False)
    r = svc.ask(9_001_001_002, "Какие витамины обсудить с ветеринаром?")
    assert r.source == "billing_block"
    billing.check_and_consume_answer_credit.assert_not_called()
    llm.complete_with_system.assert_not_called()
    rag.retrieve.assert_not_called()


def test_ask_benign_llm_calls_consume_when_rag_empty(settings, user_id) -> None:
    svc, billing, messages, llm, rag = _service(settings, user_id=user_id)
    assistant_mid = uuid.uuid4()
    messages.add_message.side_effect = [uuid.uuid4(), assistant_mid]
    r = svc.ask(9_001_001_003, "Какие витамины обсудить с ветеринаром для питомца?")
    assert r.source == "llm"
    billing.check_and_consume_answer_credit.assert_called_once_with(
        9_001_001_003, "llm", idempotency_key=str(assistant_mid)
    )
    rag.retrieve.assert_called_once()
    llm.complete.assert_called_once()


def test_ask_llm_error_user_friendly_no_stack_in_result(settings, user_id) -> None:
    from vetvopros.services.llm_service import LlmError

    svc, billing, _, llm, _ = _service(settings, user_id=user_id)
    llm.complete.side_effect = LlmError("timeout")
    r = svc.ask(9_001_001_004, "ОРВИ и температура")
    assert r.source == "error"
    assert "traceback" not in r.text.casefold()
    assert "LlmError" not in r.text
    billing.check_and_consume_answer_credit.assert_not_called()


def test_chargeable_sources_exclude_guardrail_and_block(settings) -> None:
    """D2: списание только для тарифицируемых source (см. [billing] chargeable_answer_sources)."""
    from vetvopros.services.billing_service import SqlBillingService

    svc = SqlBillingService(settings, MagicMock())
    assert svc._billable_source("guardrail") is False
    assert svc._billable_source("billing_block") is False
    assert svc._billable_source("error") is False
    assert svc._billable_source("llm") is True
