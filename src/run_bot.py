#!/usr/bin/env python3
"""Telegram bot: aiogram 3.x long polling (см. 05_bot_logic.md, agents/agent_03)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vetvopros.bot.app_factory import create_bot_and_dispatcher
from vetvopros.config.settings import get_settings
from vetvopros.db.schema import ensure_bot_schema
from vetvopros.db.session import create_engine_and_session_factory
from vetvopros.repositories.user_repo import UserRepository
from vetvopros.utils.logging import get_logger, setup_logging

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, environment=settings.environment)
    settings.validate_for_bot()
    engine, session_factory = create_engine_and_session_factory(
        settings.database_url,
        pool_size=settings.database_pool_size,
    )
    ensure_bot_schema(
        engine,
        repo_root=REPO_ROOT,
        database_url=settings.database_url,
        environment=settings.environment,
    )
    users_repo = UserRepository(session_factory)
    await asyncio.to_thread(users_repo.clear_all_disclaimers)
    try:
        bot, dp = create_bot_and_dispatcher(settings, session_factory)
        log.info(
            "bot_polling_start",
            extra={
                "structured": {
                    "app": settings.app_name,
                    "environment": settings.environment,
                    "config_ini": str(settings.config_ini_path),
                }
            },
        )
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await asyncio.to_thread(users_repo.clear_all_disclaimers)
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
