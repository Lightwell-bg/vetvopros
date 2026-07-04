from aiogram import Dispatcher

from vetvopros.handlers.analyses import router as analyses_router
from vetvopros.handlers.callbacks import router as callbacks_router
from vetvopros.handlers.chat import router as chat_router
from vetvopros.handlers.fallback import router as fallback_router
from vetvopros.handlers.nav import router as nav_router
from vetvopros.handlers.specialist_relay import router as specialist_relay_router
from vetvopros.handlers.start_help import router as start_help_router


def register_handlers(dp: Dispatcher) -> None:
    # Релей специалиста и сессия — до общей навигации (перехват NAV_SPECIALIST в активной сессии)
    dp.include_router(specialist_relay_router)
    dp.include_router(start_help_router)
    dp.include_router(nav_router)
    dp.include_router(callbacks_router)
    dp.include_router(analyses_router)
    dp.include_router(chat_router)
    dp.include_router(fallback_router)
