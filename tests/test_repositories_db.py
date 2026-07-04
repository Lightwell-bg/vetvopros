"""Интеграционные проверки репозиториев (нужен PostgreSQL + pgvector)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from vetvopros.db.constants import EMBEDDING_DIMENSIONS
from vetvopros.repositories import (
    AuditRepository,
    BillingRepository,
    ChunkRepository,
    DocumentRepository,
    MessageRepository,
    UserRepository,
)


def _unit_embedding(first: float = 1.0) -> list[float]:
    v = [0.0] * EMBEDDING_DIMENSIONS
    v[0] = first
    return v


@pytest.mark.integration
def test_user_document_chunk_message_audit_billing(session_factory: sessionmaker) -> None:
    users = UserRepository(session_factory)
    docs = DocumentRepository(session_factory)
    chunks = ChunkRepository(session_factory)
    messages = MessageRepository(session_factory)
    audit = AuditRepository(session_factory)
    billing = BillingRepository(session_factory)

    tg = 9_000_000_000 + (uuid.uuid4().int % 1_000_000_000)
    user = users.get_or_create(tg, username="pytest_user")
    uid = user.id

    bal = billing.get_balance(uid)
    assert bal is not None

    doc = docs.create(
        title="T",
        slug=f"pytest-{uuid.uuid4().hex[:12]}",
        body_markdown="# x",
        status="published",
    )
    emb = _unit_embedding(1.0)
    ch = chunks.insert_chunk(document_id=doc.id, chunk_index=0, content="hello", embedding=emb)
    assert ch.document_id == doc.id

    found = chunks.search_similar(_unit_embedding(1.0), limit=3)
    assert any(c.id == ch.id for c, _d in found)

    messages.add_message(user_id=uid, role="user", content="hi", source="llm", metadata={})
    hist = messages.list_for_user(uid, limit=10)
    assert len(hist) >= 1

    log = audit.append(user_id=uid, event_type="pytest_crud", details={"ok": True})
    assert log.user_id == uid

    plan = billing.create_plan(code=f"pt_{uuid.uuid4().hex[:8]}", name="P", monthly_answer_quota=10)
    sub = billing.create_subscription(
        user_id=uid,
        plan_id=plan.id,
        status="active",
    )
    assert sub.plan_id == plan.id
    active = billing.list_active_subscriptions(uid)
    assert any(s.id == sub.id for s in active)

    pay = billing.create_payment(
        user_id=uid,
        provider="stub",
        provider_payment_id=f"stub_{uuid.uuid4().hex}",
        status="pending",
    )
    assert billing.get_payment_by_provider_id(pay.provider_payment_id) is not None

    draft_doc = docs.create(
        title="Draft",
        slug=f"pytest-draft-{uuid.uuid4().hex[:12]}",
        body_markdown="# d",
        status="draft",
    )
    draft_emb = _unit_embedding(0.3)
    draft_ch = chunks.insert_chunk(
        document_id=draft_doc.id,
        chunk_index=0,
        content="draft only",
        embedding=draft_emb,
    )
    found_draft = chunks.search_similar(draft_emb, limit=10)
    assert not any(c.id == draft_ch.id for c, _d in found_draft)

    docs.delete(draft_doc.id)
    docs.delete(doc.id)
