"""Заглушка платёжного провайдера (MVP): создание записи платежа и разбор «вебхука».

Реальные секреты провайдера — только в `.env` (см. `PAYMENT_PROVIDER`, `PAYMENT_WEBHOOK_SECRET`).
Идемпотентность начисления обеспечивается уникальным `provider_payment_id` и статусом `completed` в БД.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal


PROVIDER_STUB = "stub"


def new_stub_provider_payment_id() -> str:
    return f"stub_{uuid.uuid4().hex}"


def pack_payload(*, pack_size: int) -> dict[str, Any]:
    return {"kind": "pack", "pack_size": int(pack_size)}


def subscription_payload(*, plan_code: str, duration_days: int = 30) -> dict[str, Any]:
    return {"kind": "subscription", "plan_code": str(plan_code), "duration_days": int(duration_days)}


def combo_pack_payload(*, ai_credits: int, specialist_credits: int) -> dict[str, Any]:
    return {
        "kind": "combo_pack",
        "ai_credits": int(ai_credits),
        "specialist_credits": int(specialist_credits),
    }


@dataclass(frozen=True)
class StubWebhookEvent:
    provider_payment_id: str
    event: Literal["completed", "failed"]
    reason: str | None = None


def parse_stub_webhook(body: dict[str, Any]) -> StubWebhookEvent:
    """Разбор JSON тела фиктивного вебхука.

    Ожидаемые поля:
    - ``provider_payment_id``: str
    - ``event``: ``"completed"`` | ``"failed"``
    - ``reason``: опционально при ``failed``
    """
    pid = body.get("provider_payment_id")
    if not isinstance(pid, str) or not pid.strip():
        msg = "stub webhook: missing provider_payment_id"
        raise ValueError(msg)
    ev = body.get("event")
    if ev not in ("completed", "failed"):
        msg = f"stub webhook: invalid event: {ev!r}"
        raise ValueError(msg)
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        msg = "stub webhook: reason must be str or omitted"
        raise ValueError(msg)
    return StubWebhookEvent(provider_payment_id=pid.strip(), event=ev, reason=reason)


def create_payment(
    *,
    pack_size: int | None = None,
    plan_code: str | None = None,
    combo_ai_credits: int | None = None,
    combo_specialist_credits: int | None = None,
    duration_days: int = 30,
) -> tuple[str, dict[str, Any]]:
    """Собрать ``provider_payment_id`` и ``payload`` для строки ``payments`` (без записи в БД).

    Ровно одно из: ``pack_size``, ``plan_code`` или пара ``combo_ai_credits`` + ``combo_specialist_credits``.
    """
    pid = new_stub_provider_payment_id()
    n_opts = sum(
        1
        for x in (pack_size, plan_code, combo_ai_credits, combo_specialist_credits)
        if x is not None
    )
    if combo_ai_credits is not None or combo_specialist_credits is not None:
        if pack_size is not None or plan_code is not None:
            msg = "create_payment: combo pack is mutually exclusive with pack_size/plan_code"
            raise ValueError(msg)
        if combo_ai_credits is None or combo_specialist_credits is None:
            msg = "create_payment: combo needs both combo_ai_credits and combo_specialist_credits"
            raise ValueError(msg)
        return pid, combo_pack_payload(
            ai_credits=combo_ai_credits,
            specialist_credits=combo_specialist_credits,
        )
    if n_opts > 1:
        msg = "create_payment: specify only one purchase type"
        raise ValueError(msg)
    if pack_size is not None:
        return pid, pack_payload(pack_size=pack_size)
    if plan_code is not None:
        return pid, subscription_payload(plan_code=plan_code, duration_days=duration_days)
    msg = "create_payment: need pack_size, plan_code, or combo credits"
    raise ValueError(msg)
