"""Bot + Dispatcher wiring."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from sqlalchemy.orm import Session, sessionmaker

from vetvopros.bot.deps import BotDeps
from vetvopros.bot.middleware import DepsMiddleware
from vetvopros.bot.specialist_registry import SpecialistRegistry
from vetvopros.config.settings import Settings
from vetvopros.config.specialists import load_specialists
from vetvopros.handlers import register_handlers
from vetvopros.repositories.chunk_repo import ChunkRepository
from vetvopros.repositories.document_repo import DocumentRepository
from vetvopros.repositories.message_repo import MessageRepository
from vetvopros.repositories.relay_repo import RelayRepository
from vetvopros.repositories.user_repo import UserRepository
from vetvopros.services.answer_service import VetAnswerService
from vetvopros.services.billing_service import SqlBillingService
from vetvopros.services.llm_service import LlmService
from vetvopros.services.rag_service import RagService, default_embedder


def create_bot_and_dispatcher(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> tuple[Bot, Dispatcher]:
    users = UserRepository(session_factory)
    billing = SqlBillingService(settings, session_factory)
    messages = MessageRepository(session_factory)
    relay = RelayRepository(session_factory)
    llm = LlmService(settings)
    rag = RagService(
        settings,
        documents=DocumentRepository(session_factory),
        chunks=ChunkRepository(session_factory),
        embedder=default_embedder(settings),
    )
    answer = VetAnswerService(settings, users, billing, messages, llm, rag)
    cards = load_specialists(settings.config_ini_path)
    specialist_registry = SpecialistRegistry(cards=cards)
    deps = BotDeps(
        settings=settings,
        users=users,
        billing=billing,
        answer=answer,
        specialist_registry=specialist_registry,
        relay=relay,
    )

    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DepsMiddleware(deps))
    register_handlers(dp)

    @dp.startup.register
    async def _startup(bot: Bot) -> None:
        await specialist_registry.prime_all(bot)
        cmds = [
            BotCommand(command="start", description="Старт и условия использования"),
            BotCommand(command="help", description="Справка"),
            BotCommand(command="cabinet", description="Личный кабинет"),
            BotCommand(command="cancel", description="Выйти из диалога с ветеринаром"),
            BotCommand(command="restart", description="Сброс сценария и меню"),
        ]
        if settings.features.enable_analyses_flow:
            cmds.append(BotCommand(command="analyses", description="Анализы питомца"))
        if settings.features.enable_specialist_menu:
            cmds.append(BotCommand(command="specialist", description="Ветеринары-специалисты"))
        await bot.set_my_commands(cmds)

    return bot, dp
