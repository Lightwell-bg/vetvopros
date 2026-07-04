"""FastAPI admin: healthcheck, сессии, CRUD документов, статус, audit."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from vetvopros.admin.routes_web import router as web_router
from vetvopros.config.settings import get_settings
from vetvopros.db.session import check_database, create_engine_and_session_factory
from vetvopros.utils.logging import get_logger, setup_logging

log = get_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _db_resources() -> tuple[Engine, sessionmaker[Session]]:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine, _session_factory = create_engine_and_session_factory(
            settings.database_url,
            pool_size=settings.database_pool_size,
        )
    return _engine, _session_factory


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, environment=settings.environment)
    log.info(
        "admin_start",
        extra={"structured": {"app": settings.app_name, "environment": settings.environment}},
    )
    engine, session_factory = _db_resources()
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = settings
    yield
    dispose_engine()
    app.state.engine = None
    app.state.session_factory = None


app = FastAPI(title="VetVopros Admin", lifespan=lifespan)

_settings_for_mw = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=_settings_for_mw.admin_session_secret,
    session_cookie="vetvopros_admin",
    same_site="lax",
    https_only=False,
)

app.include_router(web_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Return 200 when PostgreSQL is reachable; 503 if the DB check fails."""
    engine, _ = _db_resources()
    if check_database(engine):
        return {"status": "ok", "database": "up"}
    raise HTTPException(
        status_code=503,
        detail={"status": "degraded", "database": "down"},
    )
