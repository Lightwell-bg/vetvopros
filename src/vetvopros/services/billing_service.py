"""Billing: AI-ответы + отдельная квота сообщений специалисту (релей)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.billing.provider_stub import (
    PROVIDER_STUB,
    StubWebhookEvent,
    create_payment as stub_create_payment,
    parse_stub_webhook,
)
from vetvopros.config.settings import Settings
from vetvopros.db.models import (
    AuditLog,
    Payment,
    Subscription,
    SubscriptionPlan,
    User,
    UserBalance,
)
from vetvopros.db.session import session_scope
from vetvopros.repositories.audit_repo import AuditRepository
from vetvopros.repositories.billing_repo import BillingRepository
from vetvopros.services.protocols import CabinetSnapshot

log = logging.getLogger(__name__)


def _chargeable_sources(ini: str) -> frozenset[str]:
    return frozenset(x.strip() for x in ini.split(",") if x.strip())


class SqlBillingService:
    def __init__(
        self, settings: Settings, session_factory: sessionmaker[Session]
    ) -> None:
        self._settings = settings
        self._factory = session_factory
        self._billing = BillingRepository(session_factory)
        self._audit = AuditRepository(session_factory)

    def _billable_source(self, source_type: str) -> bool:
        return source_type in _chargeable_sources(
            self._settings.billing.chargeable_answer_sources
        )

    def _is_admin(self, telegram_id: int) -> bool:
        return telegram_id in (getattr(self._settings, "telegram_admin_ids", []) or [])

    def ensure_user_balance(self, telegram_id: int) -> None:
        """Гарантирует ``users`` + ``user_balances`` для telegram_id (если записи ещё нет)."""
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                user = User(telegram_id=telegram_id, username=None)
                s.add(user)
                s.flush()
            bal = s.scalar(select(UserBalance).where(UserBalance.user_id == user.id))
            if bal is None:
                s.add(UserBalance(user_id=user.id))

    def check_and_consume_answer_credit(
        self,
        telegram_id: int,
        source_type: str,
        *,
        idempotency_key: str | None = None,
    ) -> bool:
        """Списать одну единицу ответа, если источник тарифицируемый.

        Приоритет: **бесплатный лимит** → подписка (**безлимит ИИ** или квота ``monthly_answer_quota``)
        → **пакет** ``pack_credits``.
        Нетарифицируемые ``source_type`` — без списания, возвращает True.
        При исчерпании лимита — False (WARNING в лог).
        """
        if self._is_admin(telegram_id):
            return True
        if not self._billable_source(source_type):
            return True

        now = datetime.now(UTC)
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == telegram_id))
            if user is None:
                user = User(telegram_id=telegram_id, username=None)
                s.add(user)
                s.flush()
                s.add(UserBalance(user_id=user.id))
                s.flush()

            if idempotency_key:
                dup = s.scalar(
                    select(AuditLog.id)
                    .where(
                        AuditLog.user_id == user.id,
                        AuditLog.event_type == "answer_spend",
                        func.jsonb_extract_path_text(
                            AuditLog.details, literal("idempotency_key")
                        )
                        == idempotency_key,
                    )
                    .limit(1)
                )
                if dup is not None:
                    return True

            bal = s.scalar(
                select(UserBalance)
                .where(UserBalance.user_id == user.id)
                .with_for_update()
            )
            if bal is None:
                bal = UserBalance(user_id=user.id)
                s.add(bal)
                s.flush()

            rows = list(
                s.execute(
                    select(Subscription, SubscriptionPlan)
                    .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
                    .where(
                        Subscription.user_id == user.id,
                        Subscription.status == "active",
                        Subscription.valid_from <= now,
                        Subscription.valid_until >= now,
                    )
                    .order_by(Subscription.valid_until.desc())
                    .with_for_update(of=[Subscription])
                ).all()
            )

            free_lim = max(0, self._settings.billing.free_answers_per_user)

            if bal.free_used_total < free_lim:
                bal.free_used_total += 1
                details: dict = {
                    "source": source_type,
                    "subscription": False,
                    "bucket": "free",
                }
                if idempotency_key:
                    details["idempotency_key"] = idempotency_key
                s.add(
                    AuditLog(
                        user_id=user.id, event_type="answer_spend", details=details
                    )
                )
                log.info(
                    "billing_answer_spend free user=%s source=%s", user.id, source_type
                )
                return True

            for sub, plan in rows:
                if plan.unlimited_ai:
                    details = {
                        "source": source_type,
                        "subscription": True,
                        "bucket": "subscription_unlimited_ai",
                        "subscription_id": str(sub.id),
                    }
                    if idempotency_key:
                        details["idempotency_key"] = idempotency_key
                    s.add(
                        AuditLog(
                            user_id=user.id, event_type="answer_spend", details=details
                        )
                    )
                    log.info(
                        "billing_answer_spend subscription_unlimited_ai user=%s source=%s",
                        user.id,
                        source_type,
                    )
                    return True
                if (
                    plan.monthly_answer_quota > 0
                    and sub.subscription_answers_used < plan.monthly_answer_quota
                ):
                    sub.subscription_answers_used += 1
                    details = {
                        "source": source_type,
                        "subscription": True,
                        "bucket": "subscription_quota_ai",
                        "subscription_id": str(sub.id),
                    }
                    if idempotency_key:
                        details["idempotency_key"] = idempotency_key
                    s.add(
                        AuditLog(
                            user_id=user.id, event_type="answer_spend", details=details
                        )
                    )
                    log.info(
                        "billing_answer_spend subscription_quota_ai user=%s source=%s",
                        user.id,
                        source_type,
                    )
                    return True

            if bal.pack_credits > 0:
                bal.pack_credits -= 1
                details = {
                    "source": source_type,
                    "subscription": False,
                    "bucket": "pack",
                }
                if idempotency_key:
                    details["idempotency_key"] = idempotency_key
                s.add(
                    AuditLog(
                        user_id=user.id, event_type="answer_spend", details=details
                    )
                )
                log.info(
                    "billing_answer_spend pack user=%s source=%s", user.id, source_type
                )
                return True

        log.warning(
            "billing_limit_exceeded telegram_id=%s source=%s",
            telegram_id,
            source_type,
        )
        return False

    def can_answer(self, user_id: int) -> bool:
        if self._is_admin(user_id):
            return True
        free_lim = max(0, self._settings.billing.free_answers_per_user)
        now = datetime.now(UTC)
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == user_id))
            if user is None:
                return free_lim > 0
            bal = s.scalar(select(UserBalance).where(UserBalance.user_id == user.id))
            sub_rows = list(
                s.execute(
                    select(Subscription, SubscriptionPlan)
                    .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
                    .where(
                        Subscription.user_id == user.id,
                        Subscription.status == "active",
                        Subscription.valid_from <= now,
                        Subscription.valid_until >= now,
                    )
                    .order_by(Subscription.valid_until.desc())
                ).all()
            )
            used = bal.free_used_total if bal else 0
            if free_lim - used > 0:
                return True
            for sub, plan in sub_rows:
                if plan.unlimited_ai:
                    return True
                if (
                    plan.monthly_answer_quota > 0
                    and sub.subscription_answers_used < plan.monthly_answer_quota
                ):
                    return True
            if bal is not None and bal.pack_credits > 0:
                return True
            return False

    def _balance_for(
        self, s: Session, telegram_id: int
    ) -> tuple[User | None, UserBalance | None]:
        user = s.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            return None, None
        bal = s.scalar(select(UserBalance).where(UserBalance.user_id == user.id))
        return user, bal

    def can_send_specialist_message(self, user_id: int) -> bool:
        if self._is_admin(user_id):
            return True
        cost = max(1, self._settings.billing.specialist_message_cost)
        free_lim = max(0, self._settings.billing.free_specialist_messages_per_user)
        now = datetime.now(UTC)
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == user_id))
            if user is None:
                return free_lim >= cost
            bal = s.scalar(select(UserBalance).where(UserBalance.user_id == user.id))
            sp_used = bal.specialist_free_used if bal else 0
            remaining_free_units = max(0, free_lim - sp_used)
            if remaining_free_units >= cost:
                return True
            need = cost - remaining_free_units
            sub_rows = list(
                s.execute(
                    select(Subscription, SubscriptionPlan)
                    .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
                    .where(
                        Subscription.user_id == user.id,
                        Subscription.status == "active",
                        Subscription.valid_from <= now,
                        Subscription.valid_until >= now,
                    )
                    .order_by(Subscription.valid_until.desc())
                ).all()
            )
            rem = need
            for sub, plan in sub_rows:
                cap = int(plan.specialist_units_included_per_period or 0)
                if cap <= 0:
                    continue
                room = max(0, cap - sub.subscription_specialist_used)
                take = min(rem, room)
                rem -= take
                if rem <= 0:
                    return True
            pack = bal.specialist_pack_credits if bal else 0
            return pack >= rem

    def record_specialist_message(self, user_id: int) -> None:
        if self._is_admin(user_id):
            return
        cost = max(1, self._settings.billing.specialist_message_cost)
        free_lim = max(0, self._settings.billing.free_specialist_messages_per_user)
        now = datetime.now(UTC)
        with session_scope(self._factory) as s:
            user, bal = self._balance_for(s, user_id)
            if user is None:
                user = User(telegram_id=user_id, username=None)
                s.add(user)
                s.flush()
            if bal is None:
                bal = UserBalance(user_id=user.id)
                s.add(bal)
                s.flush()
            bal = s.scalar(
                select(UserBalance)
                .where(UserBalance.user_id == user.id)
                .with_for_update()
            )
            assert bal is not None
            remaining_free_units = max(0, free_lim - bal.specialist_free_used)
            take_free = min(cost, remaining_free_units)
            need = cost - take_free
            bal.specialist_free_used += take_free
            from_sub = 0
            from_pack = 0
            if need > 0:
                sub_rows = list(
                    s.execute(
                        select(Subscription, SubscriptionPlan)
                        .join(
                            SubscriptionPlan,
                            Subscription.plan_id == SubscriptionPlan.id,
                        )
                        .where(
                            Subscription.user_id == user.id,
                            Subscription.status == "active",
                            Subscription.valid_from <= now,
                            Subscription.valid_until >= now,
                        )
                        .order_by(Subscription.valid_until.desc())
                        .with_for_update(of=[Subscription])
                    ).all()
                )
                for sub, plan in sub_rows:
                    if need <= 0:
                        break
                    cap = int(plan.specialist_units_included_per_period or 0)
                    if cap <= 0:
                        continue
                    room = max(0, cap - sub.subscription_specialist_used)
                    if room <= 0:
                        continue
                    take = min(need, room)
                    sub.subscription_specialist_used += take
                    from_sub += take
                    need -= take
            if need > 0:
                from_pack = need
                if bal.specialist_pack_credits < from_pack:
                    log.error(
                        "specialist_pack_overdraw user=%s need=%s have=%s",
                        user.id,
                        from_pack,
                        bal.specialist_pack_credits,
                    )
                    from_pack = max(0, bal.specialist_pack_credits)
                bal.specialist_pack_credits -= from_pack
                need -= from_pack
            s.add(
                AuditLog(
                    user_id=user.id,
                    event_type="specialist_spend",
                    details={
                        "from_free_units": take_free,
                        "from_subscription_units": from_sub,
                        "from_pack_credits": from_pack,
                        "cost": cost,
                    },
                )
            )

    def get_cabinet_snapshot(self, user_id: int) -> CabinetSnapshot:
        limit = self._settings.billing.free_answers_per_user
        sp_lim = self._settings.billing.free_specialist_messages_per_user
        now = datetime.now(UTC)
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == user_id))
            if user is None:
                user = User(telegram_id=user_id, username=None)
                s.add(user)
                s.flush()
                s.add(UserBalance(user_id=user.id))
                s.flush()
            bal = s.scalar(select(UserBalance).where(UserBalance.user_id == user.id))
            used = bal.free_used_total if bal else 0
            pack = bal.pack_credits if bal else 0
            sp_used = bal.specialist_free_used if bal else 0
            sp_pack = bal.specialist_pack_credits if bal else 0

            sub_rows = list(
                s.execute(
                    select(Subscription, SubscriptionPlan)
                    .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
                    .where(
                        Subscription.user_id == user.id,
                        Subscription.status == "active",
                        Subscription.valid_from <= now,
                        Subscription.valid_until >= now,
                    )
                    .order_by(Subscription.valid_until.desc())
                ).all()
            )
            subscription_active = False
            cab_plan_name = cab_until = None
            cab_ai_unlim = False
            cab_fin_ai_used = cab_fin_ai_quota = None
            cab_sp_sub_used = cab_sp_sub_cap = 0
            ai_sub_name = ai_sub_used = ai_sub_quota = ai_sub_until = None
            sub_line = "Подписка: не оформлена."
            if sub_rows:
                sub, plan = sub_rows[0]
                subscription_active = True
                cab_plan_name = plan.name
                cab_until = sub.valid_until.date().isoformat()
                cab_ai_unlim = bool(plan.unlimited_ai)
                cab_sp_sub_used = int(sub.subscription_specialist_used)
                cab_sp_sub_cap = int(plan.specialist_units_included_per_period or 0)
                ai_sub_name = plan.name
                ai_sub_until = cab_until
                if cab_ai_unlim:
                    cab_fin_ai_used = None
                    cab_fin_ai_quota = None
                    ai_sub_used = 0
                    ai_sub_quota = None
                elif plan.monthly_answer_quota > 0:
                    cab_fin_ai_used = sub.subscription_answers_used
                    cab_fin_ai_quota = plan.monthly_answer_quota
                    ai_sub_used = sub.subscription_answers_used
                    ai_sub_quota = plan.monthly_answer_quota
                else:
                    cab_fin_ai_used = 0
                    cab_fin_ai_quota = 0
                    ai_sub_used = 0
                    ai_sub_quota = 0
                bits = [f"{plan.name} до {sub.valid_until.date().isoformat()}"]
                if cab_ai_unlim:
                    bits.append("ИИ безлимит")
                elif plan.monthly_answer_quota > 0:
                    bits.append(
                        f"ИИ {sub.subscription_answers_used} из {plan.monthly_answer_quota} за период"
                    )
                if cab_sp_sub_cap > 0:
                    bits.append(
                        f"специалист {sub.subscription_specialist_used} из {cab_sp_sub_cap} ед. за период"
                    )
                sub_line = "Подписка: " + "; ".join(bits) + "."
            n_spend = s.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.user_id == user.id, AuditLog.event_type == "answer_spend"
                )
            )
            lifetime_spends = int(n_spend or 0)
            n_pack_ai = s.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.user_id == user.id,
                    AuditLog.event_type == "answer_spend",
                    AuditLog.details.contains({"bucket": "pack"}),
                )
            )
            ai_pack_used = int(n_pack_ai or 0)
            ai_pack_cap = ai_pack_used + int(pack)
            sp_details = s.scalars(
                select(AuditLog.details).where(
                    AuditLog.user_id == user.id,
                    AuditLog.event_type == "specialist_spend",
                )
            ).all()
            sp_pack_used_units = 0
            for d in sp_details:
                if isinstance(d, dict):
                    sp_pack_used_units += int(d.get("from_pack_credits") or 0)
            sp_pack_cap = sp_pack_used_units + int(sp_pack)
        return CabinetSnapshot(
            free_used=used,
            free_limit=limit,
            pack_credits=pack,
            specialist_free_used=sp_used,
            specialist_free_limit=sp_lim,
            specialist_pack_credits=sp_pack,
            subscription_line=sub_line,
            ai_subscription_name=ai_sub_name,
            ai_subscription_used=ai_sub_used,
            ai_subscription_quota=ai_sub_quota,
            ai_subscription_until=ai_sub_until,
            subscription_active=subscription_active,
            subscription_plan_name=cab_plan_name,
            subscription_until_iso=cab_until,
            subscription_ai_unlimited=cab_ai_unlim,
            subscription_finite_ai_used=cab_fin_ai_used,
            subscription_finite_ai_quota=cab_fin_ai_quota,
            subscription_specialist_used=cab_sp_sub_used,
            subscription_specialist_cap=cab_sp_sub_cap,
            billing_bypass_admin=self._is_admin(user_id),
            lifetime_answer_spends=lifetime_spends,
            ai_pack_answers_used=ai_pack_used,
            ai_pack_answers_capacity=ai_pack_cap,
            specialist_pack_units_used=sp_pack_used_units,
            specialist_pack_units_capacity=sp_pack_cap,
        )

    def create_stub_pack_payment(self, telegram_id: int, pack_size: int) -> str:
        """Создать pending-платёж на пакет ответов; вернуть ``provider_payment_id``."""
        self.ensure_user_balance(telegram_id)
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == telegram_id))
            assert user is not None
        pid, payload = stub_create_payment(pack_size=pack_size)
        self._billing.create_payment(
            user_id=user.id,
            provider=PROVIDER_STUB,
            provider_payment_id=pid,
            status="pending",
            payload=payload,
        )
        return pid

    def create_stub_combo_pack_payment(
        self,
        telegram_id: int,
        *,
        ai_credits: int,
        specialist_credits: int,
    ) -> str:
        """Pending-платёж: пакет «N запросов к ИИ + M единиц специалиста»."""
        self.ensure_user_balance(telegram_id)
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == telegram_id))
            assert user is not None
        pid, payload = stub_create_payment(
            combo_ai_credits=ai_credits,
            combo_specialist_credits=specialist_credits,
        )
        self._billing.create_payment(
            user_id=user.id,
            provider=PROVIDER_STUB,
            provider_payment_id=pid,
            status="pending",
            payload=payload,
        )
        return pid

    def create_stub_subscription_payment(
        self,
        telegram_id: int,
        plan_code: str,
        *,
        duration_days: int = 30,
    ) -> str:
        """Создать pending-платёж на активацию подписки по коду плана."""
        self.ensure_user_balance(telegram_id)
        with session_scope(self._factory) as s:
            user = s.scalar(select(User).where(User.telegram_id == telegram_id))
            assert user is not None
        pid, payload = stub_create_payment(
            plan_code=plan_code, duration_days=duration_days
        )
        self._billing.create_payment(
            user_id=user.id,
            provider=PROVIDER_STUB,
            provider_payment_id=pid,
            status="pending",
            payload=payload,
        )
        return pid

    def _apply_completed_payment(self, s: Session, pay: Payment) -> None:
        user = s.get(User, pay.user_id)
        if user is None:
            msg = "payment user missing"
            raise RuntimeError(msg)
        payload = pay.payload or {}
        kind = payload.get("kind")
        if kind == "pack":
            size = int(payload.get("pack_size", 0))
            if size <= 0:
                msg = "invalid pack_size"
                raise ValueError(msg)
            bal = s.scalar(
                select(UserBalance)
                .where(UserBalance.user_id == user.id)
                .with_for_update()
            )
            if bal is None:
                bal = UserBalance(user_id=user.id)
                s.add(bal)
                s.flush()
            bal.pack_credits += size
            s.add(
                AuditLog(
                    user_id=user.id,
                    event_type="payment_completed",
                    details={"payment_id": str(pay.id), "pack_size": size},
                )
            )
            log.info("billing_payment_completed pack user=%s size=%s", user.id, size)
            return
        if kind == "combo_pack":
            ai_c = int(payload.get("ai_credits", 0))
            sp_c = int(payload.get("specialist_credits", 0))
            if ai_c <= 0 and sp_c <= 0:
                msg = "invalid combo_pack credits"
                raise ValueError(msg)
            bal = s.scalar(
                select(UserBalance)
                .where(UserBalance.user_id == user.id)
                .with_for_update()
            )
            if bal is None:
                bal = UserBalance(user_id=user.id)
                s.add(bal)
                s.flush()
            bal.pack_credits += max(0, ai_c)
            bal.specialist_pack_credits += max(0, sp_c)
            s.add(
                AuditLog(
                    user_id=user.id,
                    event_type="payment_completed",
                    details={
                        "payment_id": str(pay.id),
                        "kind": "combo_pack",
                        "ai_credits": ai_c,
                        "specialist_credits": sp_c,
                    },
                )
            )
            log.info(
                "billing_payment_completed combo_pack user=%s ai=%s specialist=%s",
                user.id,
                ai_c,
                sp_c,
            )
            return
        if kind == "subscription":
            plan_code = payload.get("plan_code")
            if not plan_code or not isinstance(plan_code, str):
                msg = "invalid plan_code"
                raise ValueError(msg)
            duration_days = int(payload.get("duration_days", 30))
            plan = s.scalar(
                select(SubscriptionPlan).where(SubscriptionPlan.code == plan_code)
            )
            if plan is None:
                msg = f"unknown plan_code={plan_code!r}"
                raise ValueError(msg)
            now = datetime.now(UTC)
            sub = Subscription(
                user_id=user.id,
                plan_id=plan.id,
                status="active",
                valid_from=now,
                valid_until=now + timedelta(days=max(1, duration_days)),
                subscription_answers_used=0,
                subscription_specialist_used=0,
            )
            s.add(sub)
            s.flush()
            s.add(
                AuditLog(
                    user_id=user.id,
                    event_type="payment_completed",
                    details={"payment_id": str(pay.id), "plan_code": plan_code},
                )
            )
            s.add(
                AuditLog(
                    user_id=user.id,
                    event_type="subscription_activated",
                    details={
                        "plan_code": plan_code,
                        "until": sub.valid_until.isoformat(),
                        "subscription_id": str(sub.id),
                    },
                )
            )
            log.info(
                "billing_subscription_activated user=%s plan=%s", user.id, plan_code
            )
            return
        msg = f"unknown payment payload kind: {kind!r}"
        raise ValueError(msg)

    def confirm_stub_payment(self, provider_payment_id: str) -> bool:
        """Ручное подтверждение демо-платежа; идемпотентно."""
        with session_scope(self._factory) as s:
            pay = s.scalar(
                select(Payment)
                .where(Payment.provider_payment_id == provider_payment_id)
                .with_for_update()
            )
            if pay is None:
                log.warning("confirm_stub_payment: unknown id=%s", provider_payment_id)
                return False
            if pay.status == "completed":
                return True
            if pay.status != "pending":
                log.warning(
                    "confirm_stub_payment: bad status=%s id=%s",
                    pay.status,
                    provider_payment_id,
                )
                return False
            self._apply_completed_payment(s, pay)
            pay.status = "completed"
        return True

    def process_stub_webhook(self, body: dict) -> bool:
        """Разобрать тело вебхука заглушки и обновить платёж (completed / failed)."""
        try:
            ev = parse_stub_webhook(body)
        except ValueError as e:
            log.error("stub_webhook_parse_error: %s", e)
            return False
        return self._process_stub_webhook_event(ev)

    def _process_stub_webhook_event(self, ev: StubWebhookEvent) -> bool:
        if ev.event == "failed":
            with session_scope(self._factory) as s:
                pay = s.scalar(
                    select(Payment)
                    .where(Payment.provider_payment_id == ev.provider_payment_id)
                    .with_for_update()
                )
                if pay is None:
                    return False
                if pay.status == "completed":
                    return True
                pay.status = "failed"
                merged = {**(pay.payload or {}), "fail_reason": ev.reason or ""}
                pay.payload = merged
                s.add(
                    AuditLog(
                        user_id=pay.user_id,
                        event_type="payment_failed",
                        details={"payment_id": str(pay.id), "reason": ev.reason or ""},
                    )
                )
            log.warning("billing_payment_failed id=%s", ev.provider_payment_id)
            return True
        return self.confirm_stub_payment(ev.provider_payment_id)
