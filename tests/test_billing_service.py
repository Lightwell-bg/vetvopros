"""Интеграционные тесты биллинга (PostgreSQL)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from vetvopros.config.settings import load_settings
from vetvopros.repositories.user_repo import UserRepository
from vetvopros.services.billing_service import SqlBillingService


@pytest.mark.integration
def test_billing_free_limit_and_pack(session_factory: sessionmaker) -> None:
    settings = load_settings()
    billing = SqlBillingService(settings, session_factory)
    users = UserRepository(session_factory)
    tg = 8_000_000_000 + (uuid.uuid4().int % 1_000_000_000)
    users.get_or_create(tg, username="bill_test")

    low = settings.billing.free_answers_per_user
    for i in range(low):
        assert billing.can_answer(tg) is True
        assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key=f"k{i}") is True

    assert billing.can_answer(tg) is False
    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="over") is False

    pid = billing.create_stub_pack_payment(tg, 2)
    assert billing.confirm_stub_payment(pid) is True
    assert billing.can_answer(tg) is True
    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="p1") is True


@pytest.mark.integration
def test_billing_idempotency_answer_spend(session_factory: sessionmaker) -> None:
    settings = load_settings()
    billing = SqlBillingService(settings, session_factory)
    users = UserRepository(session_factory)
    tg = 8_100_000_000 + (uuid.uuid4().int % 1_000_000_000)
    users.get_or_create(tg, username="idem_test")

    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="same") is True
    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="same") is True


@pytest.mark.integration
def test_combo_pack_payment(session_factory: sessionmaker) -> None:
    settings = load_settings()
    billing = SqlBillingService(settings, session_factory)
    users = UserRepository(session_factory)
    tg = 8_500_000_000 + (uuid.uuid4().int % 1_000_000_000)
    users.get_or_create(tg, username="combo_test")
    pid = billing.create_stub_combo_pack_payment(tg, ai_credits=7, specialist_credits=4)
    assert billing.confirm_stub_payment(pid) is True
    with session_factory() as s:
        from sqlalchemy import select

        from vetvopros.db.models import User, UserBalance

        u = s.scalar(select(User).where(User.telegram_id == tg))
        assert u is not None
        bal = s.scalar(select(UserBalance).where(UserBalance.user_id == u.id))
        assert bal is not None
        assert bal.pack_credits == 7
        assert bal.specialist_pack_credits == 4


@pytest.mark.integration
def test_stub_payment_idempotent(session_factory: sessionmaker) -> None:
    settings = load_settings()
    billing = SqlBillingService(settings, session_factory)
    users = UserRepository(session_factory)
    tg = 8_200_000_000 + (uuid.uuid4().int % 1_000_000_000)
    users.get_or_create(tg, username="pay_idem")

    pid = billing.create_stub_pack_payment(tg, 5)
    assert billing.confirm_stub_payment(pid) is True
    assert billing.confirm_stub_payment(pid) is True

    with session_factory() as s:
        from sqlalchemy import select

        from vetvopros.db.models import User, UserBalance

        u = s.scalar(select(User).where(User.telegram_id == tg))
        assert u is not None
        bal = s.scalar(select(UserBalance).where(UserBalance.user_id == u.id))
        assert bal is not None
        assert bal.pack_credits == 5


@pytest.mark.integration
def test_billing_free_before_subscription(session_factory: sessionmaker) -> None:
    """При наличии бесплатного остатка списание идёт в free, а не в подписку/пакет."""
    from sqlalchemy import select

    from vetvopros.db.models import Subscription, User, UserBalance
    from vetvopros.repositories.billing_repo import BillingRepository

    settings = load_settings()
    billing = SqlBillingService(settings, session_factory)
    users = UserRepository(session_factory)
    br = BillingRepository(session_factory)
    tg = 8_400_000_000 + (uuid.uuid4().int % 1_000_000_000)
    user = users.get_or_create(tg, username="free_first")
    br.upsert_balance(user.id, free_used_total=0, pack_credits=10)
    plan = br.create_plan(code=f"pl_{uuid.uuid4().hex[:8]}", name="Sub", monthly_answer_quota=5)
    br.create_subscription(user_id=user.id, plan_id=plan.id, status="active")

    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="ff1") is True
    with session_factory() as s:
        u = s.scalar(select(User).where(User.telegram_id == tg))
        assert u is not None
        bal = s.scalar(select(UserBalance).where(UserBalance.user_id == u.id))
        assert bal is not None
        assert bal.free_used_total == 1
        assert bal.pack_credits == 10
        sub = s.scalar(select(Subscription).where(Subscription.user_id == u.id))
        assert sub is not None
        assert sub.subscription_answers_used == 0


@pytest.mark.integration
def test_subscription_priority_over_pack_and_free(session_factory: sessionmaker) -> None:
    """После исчерпания бесплатного лимита: подписка, затем пакет."""
    settings = load_settings()
    billing = SqlBillingService(settings, session_factory)
    users = UserRepository(session_factory)
    from vetvopros.repositories.billing_repo import BillingRepository

    br = BillingRepository(session_factory)
    tg = 8_300_000_000 + (uuid.uuid4().int % 1_000_000_000)
    user = users.get_or_create(tg, username="sub_pri")
    br.upsert_balance(
        user.id,
        free_used_total=settings.billing.free_answers_per_user,
        pack_credits=3,
    )
    plan = br.create_plan(code=f"pl_{uuid.uuid4().hex[:8]}", name="Test", monthly_answer_quota=1)
    br.create_subscription(user_id=user.id, plan_id=plan.id, status="active")

    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="s1") is True
    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="s2") is True
    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="s3") is True
    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="s4") is True
    assert billing.check_and_consume_answer_credit(tg, "llm", idempotency_key="s5") is False
