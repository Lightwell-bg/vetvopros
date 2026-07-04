"""Проверка наличия таблиц и опциональный вызов Alembic upgrade."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url

log = logging.getLogger(__name__)


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _safe_database_name(name: str) -> bool:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    return bool(name) and all(ch in allowed for ch in name)


def ensure_database_exists(*, database_url: str, environment: str) -> None:
    """
    Проверить наличие БД из DATABASE_URL и при необходимости создать её.

    По умолчанию включено только в development. Можно явно переопределить
    VETVOPROS_AUTO_CREATE_DB=true|false.
    """
    env_lower = environment.strip().lower()
    auto_create = _env_flag(
        "VETVOPROS_AUTO_CREATE_DB",
        default=(env_lower == "development"),
    )
    if not auto_create:
        return

    target_url = make_url(database_url)
    db_name = target_url.database or ""
    if not db_name:
        return
    if not _safe_database_name(db_name):
        log.warning(
            "auto_create_db_skipped_unsafe_name",
            extra={"structured": {"database": db_name}},
        )
        return

    admin_url = target_url.set(database="postgres")
    admin_engine = create_engine(
        admin_url.render_as_string(hide_password=False),
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if exists:
                return
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            log.warning(
                "database_created_automatically",
                extra={"structured": {"database": db_name}},
            )
    finally:
        admin_engine.dispose()


def users_table_exists(engine: Engine) -> bool:
    try:
        insp = inspect(engine)
        return bool(insp.has_table("users"))
    except Exception:
        log.exception("schema_inspect_failed")
        return False


def run_alembic_upgrade_to_head(*, repo_root: Path, database_url: str) -> None:
    """Выполнить `alembic upgrade head` (нужен DATABASE_URL в окружении для env.py)."""
    os.environ["DATABASE_URL"] = database_url
    ini = (repo_root / "alembic.ini").resolve()
    if not ini.is_file():
        msg = f"Не найден {ini}"
        raise FileNotFoundError(msg)
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ini))
    command.upgrade(cfg, "head")


def ensure_bot_schema(
    engine: Engine,
    *,
    repo_root: Path,
    database_url: str,
    environment: str,
) -> None:
    """
    Если таблицы users нет — в development (или при VETVOPROS_AUTO_MIGRATE=true)
    запускаем Alembic upgrade; иначе выходим с подсказкой.
    """
    try:
        ensure_database_exists(database_url=database_url, environment=environment)
        engine.dispose()
    except Exception:
        log.exception("database_auto_create_failed")
        _exit_schema_help(repo_root)

    if users_table_exists(engine):
        return

    do_upgrade = _env_flag(
        "VETVOPROS_AUTO_MIGRATE",
        default=(environment.strip().lower() == "development"),
    )

    if do_upgrade:
        log.warning(
            "database_schema_missing_running_alembic",
            extra={"structured": {"repo_root": str(repo_root)}},
        )
        try:
            run_alembic_upgrade_to_head(repo_root=repo_root, database_url=database_url)
        except Exception as exc:
            log.exception("alembic_upgrade_failed")
            if _looks_like_missing_pgvector(exc):
                _exit_pgvector_help(repo_root)
            _exit_schema_help(repo_root)
        engine.dispose()
        if not users_table_exists(engine):
            log.error("schema_still_missing_after_alembic")
            _exit_schema_help(repo_root)
        log.info("database_schema_ready_after_alembic")
        return

    _exit_schema_help(repo_root)


def _exit_schema_help(repo_root: Path) -> None:
    lines = (
        "",
        "Ошибка: база/схема PostgreSQL не готова (нет БД и/или таблицы `users`).",
        "Выполните из корня репозитория (где лежат alembic.ini и .env):",
        f"  cd {repo_root}",
        "  # при необходимости создайте БД vetvopros и расширение vector",
        "  alembic upgrade head",
        "  python src/run_bot.py",
        "",
        "Автосоздание БД при старте: VETVOPROS_AUTO_CREATE_DB=true",
        "Автоприменение при старте: задайте VETVOPROS_AUTO_MIGRATE=true",
        "или в config.ini [app] environment=development (по умолчанию для dev).",
        "",
    )
    text = "\n".join(lines)
    print(text, file=sys.stderr)
    raise SystemExit(1)


def _looks_like_missing_pgvector(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "create extension if not exists vector",
        "extension \"vector\"",
        "feature not supported",
        "notsupportederror",
    )
    return any(m in text for m in markers)


def _exit_pgvector_help(repo_root: Path) -> None:
    lines = (
        "",
        "Ошибка: на сервере PostgreSQL недоступно расширение pgvector (CREATE EXTENSION vector).",
        "Авторазворачивание остановлено, потому что миграции не могут создать тип vector.",
        "",
        "Что сделать:",
        "1) Установить pgvector на сам PostgreSQL-сервер (не в Python venv).",
        "2) Повторно запустить из корня репозитория:",
        f"   cd {repo_root}",
        "   alembic upgrade head",
        "   python src/run_bot.py",
        "",
    )
    text = "\n".join(lines)
    print(text, file=sys.stderr)
    raise SystemExit(1)
