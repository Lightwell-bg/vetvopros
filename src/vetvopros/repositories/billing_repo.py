"""CRUD балансов, планов, подписок и платежей (без бизнес-правил списания)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.db.models import Payment, Subscription, SubscriptionPlan, UserBalance
from vetvopros.db.session import session_scope


class BillingRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def get_balance(self, user_id: uuid.UUID) -> UserBalance | None:
        with session_scope(self._factory) as s:
            return s.scalar(select(UserBalance).where(UserBalance.user_id == user_id))

    def upsert_balance(
        self,
        user_id: uuid.UUID,
        *,
        free_used_total: int | None = None,
        pack_credits: int | None = None,
        specialist_free_used: int | None = None,
        specialist_pack_credits: int | None = None,
    ) -> UserBalance:
        with session_scope(self._factory) as s:
            bal = s.scalar(select(UserBalance).where(UserBalance.user_id == user_id))
            if bal is None:
                bal = UserBalance(user_id=user_id)
                s.add(bal)
                s.flush()
            if free_used_total is not None:
                bal.free_used_total = free_used_total
            if pack_credits is not None:
                bal.pack_credits = pack_credits
            if specialist_free_used is not None:
                bal.specialist_free_used = specialist_free_used
            if specialist_pack_credits is not None:
                bal.specialist_pack_credits = specialist_pack_credits
            bid = bal.id
        with session_scope(self._factory) as s:
            out = s.get(UserBalance, bid)
            assert out is not None
            return out

    def list_plans(self) -> list[SubscriptionPlan]:
        with session_scope(self._factory) as s:
            return list(s.scalars(select(SubscriptionPlan).order_by(SubscriptionPlan.code)).all())

    def get_plan_by_code(self, code: str) -> SubscriptionPlan | None:
        with session_scope(self._factory) as s:
            return s.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == code))

    def create_plan(
        self,
        *,
        code: str,
        name: str,
        monthly_answer_quota: int,
        unlimited_ai: bool = False,
        specialist_units_included_per_period: int = 0,
        extra: dict | None = None,
    ) -> SubscriptionPlan:
        with session_scope(self._factory) as s:
            p = SubscriptionPlan(
                code=code,
                name=name,
                monthly_answer_quota=monthly_answer_quota,
                unlimited_ai=unlimited_ai,
                specialist_units_included_per_period=specialist_units_included_per_period,
                extra=extra or {},
            )
            s.add(p)
            s.flush()
            pid = p.id
        with session_scope(self._factory) as s:
            out = s.get(SubscriptionPlan, pid)
            assert out is not None
            return out

    def create_subscription(
        self,
        *,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
        status: str,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
    ) -> Subscription:
        now = datetime.now(UTC)
        vf = valid_from if valid_from is not None else now
        # Окно по умолчанию — сутки вперёд, иначе valid_until == now почти сразу «истекает».
        vu = valid_until if valid_until is not None else now + timedelta(days=1)
        with session_scope(self._factory) as s:
            sub = Subscription(
                user_id=user_id,
                plan_id=plan_id,
                status=status,
                valid_from=vf,
                valid_until=vu,
            )
            s.add(sub)
            s.flush()
            sid = sub.id
        with session_scope(self._factory) as s:
            out = s.get(Subscription, sid)
            assert out is not None
            return out

    def list_active_subscriptions(self, user_id: uuid.UUID, *, at: datetime | None = None) -> list[Subscription]:
        moment = at if at is not None else datetime.now(UTC)
        with session_scope(self._factory) as s:
            q = (
                select(Subscription)
                .where(
                    Subscription.user_id == user_id,
                    Subscription.status == "active",
                    Subscription.valid_from <= moment,
                    Subscription.valid_until >= moment,
                )
                .order_by(Subscription.valid_until.desc())
            )
            return list(s.scalars(q).all())

    def create_payment(
        self,
        *,
        user_id: uuid.UUID,
        provider: str,
        provider_payment_id: str,
        status: str,
        payload: dict | None = None,
    ) -> Payment:
        with session_scope(self._factory) as s:
            pay = Payment(
                user_id=user_id,
                provider=provider,
                provider_payment_id=provider_payment_id,
                status=status,
                payload=payload or {},
            )
            s.add(pay)
            s.flush()
            pid = pay.id
        with session_scope(self._factory) as s:
            out = s.get(Payment, pid)
            assert out is not None
            return out

    def get_payment_by_provider_id(self, provider_payment_id: str) -> Payment | None:
        with session_scope(self._factory) as s:
            return s.scalar(select(Payment).where(Payment.provider_payment_id == provider_payment_id))
