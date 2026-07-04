"""Dependencies injected into handler context (middleware)."""

from __future__ import annotations

from dataclasses import dataclass

from vetvopros.bot.specialist_registry import SpecialistRegistry
from vetvopros.config.settings import Settings
from vetvopros.repositories.relay_repo import RelayRepository
from vetvopros.repositories.user_repo import UserRepository
from vetvopros.services.answer_service import VetAnswerService
from vetvopros.services.billing_service import SqlBillingService


@dataclass
class BotDeps:
    settings: Settings
    users: UserRepository
    billing: SqlBillingService
    answer: VetAnswerService
    specialist_registry: SpecialistRegistry
    relay: RelayRepository
