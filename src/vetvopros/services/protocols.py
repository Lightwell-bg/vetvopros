"""Service protocols for wiring and typing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AnswerResult:
    text: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CabinetSnapshot:
    free_used: int
    free_limit: int
    pack_credits: int
    specialist_free_used: int
    specialist_free_limit: int
    specialist_pack_credits: int
    subscription_line: str
    #: Активная подписка с остатком (для кабинета); иначе поля None.
    ai_subscription_name: str | None = None
    ai_subscription_used: int | None = None
    ai_subscription_quota: int | None = None
    ai_subscription_until: str | None = None
    subscription_active: bool = False
    subscription_plan_name: str | None = None
    subscription_until_iso: str | None = None
    subscription_ai_unlimited: bool = False
    subscription_finite_ai_used: int | None = None
    subscription_finite_ai_quota: int | None = None
    subscription_specialist_used: int = 0
    subscription_specialist_cap: int = 0
    #: True если telegram_id в ``admin_ids`` — лимиты не списываются, счётчики остаются нулевыми.
    billing_bypass_admin: bool = False
    #: Сколько раз в audit зафиксировано ``answer_spend`` (подписка/пакет/бесплатно — всё вместе).
    lifetime_answer_spends: int = 0
    #: Ответы ИИ, списанные с **купленного** пакета (по ``answer_spend`` / ``bucket=pack``).
    ai_pack_answers_used: int = 0
    #: Оценка «куплено всего» для пакета ассистента: использовано + остаток ``pack_credits``.
    ai_pack_answers_capacity: int = 0
    #: Единицы пакета специалисту, списанные с ``specialist_pack_credits`` (сумма ``specialist_spend``).
    specialist_pack_units_used: int = 0
    #: Оценка ёмкости пакета специалисту: списано + остаток ``specialist_pack_credits``.
    specialist_pack_units_capacity: int = 0


@runtime_checkable
class RagSearchService(Protocol):
    def search(self, query: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
        """Return ranked chunk payloads for RAG context."""
        ...


@runtime_checkable
class LlmClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        """Chat completion from an OpenAI-compatible API."""
        ...


@runtime_checkable
class BillingService(Protocol):
    def can_answer(self, user_id: int) -> bool:
        ...

    def check_and_consume_answer_credit(
        self, user_id: int, source_type: str, *, idempotency_key: str | None = None
    ) -> bool:
        ...

    def get_cabinet_snapshot(self, user_id: int) -> CabinetSnapshot:
        ...

    def can_send_specialist_message(self, user_id: int) -> bool:
        """Есть ли квота на исходящее сообщение пациента специалисту через релей."""

    def record_specialist_message(self, user_id: int) -> None:
        ...


@runtime_checkable
class AnswerService(Protocol):
    def ask(self, user_id: int, text: str, *, username: str | None = None) -> AnswerResult:
        """Orchestrate guardrails, billing, RAG/LLM; user_id = telegram user id."""
        ...

    def ask_analysis_suggestions(
        self,
        user_id: int,
        text: str,
        *,
        username: str | None = None,
        prior_transcript: str | None = None,
    ) -> AnswerResult:
        ...

    def ask_analysis_interpretation(
        self,
        user_id: int,
        text: str,
        *,
        username: str | None = None,
        prior_transcript: str | None = None,
    ) -> AnswerResult:
        ...
