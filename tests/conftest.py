"""Общие фикстуры: PostgreSQL + применённые миграции."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env")


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    return url.strip() or None


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _database_url()
    if url is None:
        pytest.skip("DATABASE_URL не задан — интеграционные тесты БД пропущены")
    return url


@pytest.fixture(scope="session")
def session_factory(database_url: str):
    from vetvopros.db.schema import run_alembic_upgrade_to_head
    from vetvopros.db.session import create_engine_and_session_factory

    run_alembic_upgrade_to_head(repo_root=_REPO_ROOT, database_url=database_url)
    engine, factory = create_engine_and_session_factory(database_url)
    yield factory
    engine.dispose()
