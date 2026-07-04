"""SQLAlchemy engine and session factory (sync, psycopg3)."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from psycopg import ProgrammingError
from pgvector.psycopg import register_vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)


def create_engine_and_session_factory(
    database_url: str,
    *,
    pool_size: int = 5,
) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
    )

    @event.listens_for(engine, "connect")
    def _register_pgvector(dbapi_connection: object, _connection_record: object) -> None:
        try:
            register_vector(dbapi_connection)
        except ProgrammingError as exc:
            # Fresh DB can exist before Alembic creates extension `vector`.
            if "vector type not found in the database" in str(exc):
                log.warning("pgvector_type_not_found_yet_skip_registration")
                return
            raise
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, factory


def check_database(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
