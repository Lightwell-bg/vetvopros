"""Alembic environment: sync SQLAlchemy, URL from DATABASE_URL."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alembic import context
from sqlalchemy import engine_from_config, pool

from vetvopros.config.settings import load_settings
from vetvopros.db.base import Base
from vetvopros.db import models as _models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    # Keep explicit environment override for CI/one-off runs.
    url = os.environ.get("DATABASE_URL")
    if not url:
        settings = load_settings()
        url = settings.database_url
    if not (url or "").strip():
        msg = (
            "DATABASE_URL is required for alembic migrations. "
            "Set it in environment or in project .env."
        )
        raise RuntimeError(msg)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
