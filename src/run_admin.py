#!/usr/bin/env python3
"""Run FastAPI admin app with uvicorn (host/port via env or defaults)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from vetvopros.config.settings import get_settings
from vetvopros.db.schema import ensure_bot_schema
from vetvopros.db.session import create_engine_and_session_factory
from vetvopros.utils.logging import (
    get_logger,
    is_production_environment,
    setup_logging,
    uvicorn_silent_log_config,
)

log = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, environment=settings.environment)
    settings.validate_for_admin()
    engine, _ = create_engine_and_session_factory(
        settings.database_url,
        pool_size=settings.database_pool_size,
    )
    ensure_bot_schema(
        engine,
        repo_root=REPO_ROOT,
        database_url=settings.database_url,
        environment=settings.environment,
    )
    engine.dispose()

    host = settings.admin_uvicorn_host
    port = settings.admin_uvicorn_port
    reload = settings.admin_uvicorn_reload

    log.info(
        "admin_listen",
        extra={"structured": {"host": host, "port": port, "reload": reload}},
    )
    uvicorn_kwargs: dict[str, Any] = {}
    if is_production_environment(settings.environment):
        uvicorn_kwargs["log_config"] = uvicorn_silent_log_config()
        uvicorn_kwargs["access_log"] = False
    uvicorn.run(
        "vetvopros.admin.app:app",
        host=host,
        port=port,
        reload=reload,
        factory=False,
        **uvicorn_kwargs,
    )


if __name__ == "__main__":
    main()
