"""Commands: /start, /help, /cabinet, /analyses, /specialist, /restart."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from vetvopros.bot.deps import BotDeps
from vetvopros.handlers.menu_content import (
    present_start_flow,
    run_restart,
    send_analyses_prompt,
    send_cabinet_with_back,
    send_help_with_back,
    send_specialist_menu,
)

router = Router(name="start_help")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, deps: BotDeps) -> None:
    if message.from_user is None:
        return
    await state.clear()
    await present_start_flow(message, deps, message.from_user)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await send_help_with_back(message)


@router.message(Command("restart"))
async def cmd_restart(message: Message, state: FSMContext, deps: BotDeps) -> None:
    await run_restart(message, state, deps)


@router.message(Command("cabinet"), StateFilter(None))
async def cmd_cabinet(message: Message, deps: BotDeps) -> None:
    if message.from_user is None:
        return
    if not deps.users.disclaimer_accepted(message.from_user.id):
        await message.answer("Сначала примите дисклеймер через /start.")
        return
    await send_cabinet_with_back(message, deps)


@router.message(Command("analyses"), StateFilter(None))
async def cmd_analyses(message: Message, deps: BotDeps) -> None:
    if message.from_user is None:
        return
    if not deps.settings.features.enable_analyses_flow:
        await message.answer("Сценарии анализов отключены в конфигурации.")
        return
    if not deps.users.disclaimer_accepted(message.from_user.id):
        await message.answer("Сначала примите дисклеймер через /start.")
        return
    await send_analyses_prompt(message)


@router.message(Command("specialist"), StateFilter(None))
async def cmd_specialist(message: Message, deps: BotDeps) -> None:
    if message.from_user is None:
        return
    if not deps.settings.features.enable_specialist_menu:
        await message.answer("Меню специалистов отключено в конфигурации.")
        return
    if not deps.specialist_registry.cards:
        await message.answer("Специалисты не заданы в config.ini (секции specialist_*).")
        return
    if not deps.users.disclaimer_accepted(message.from_user.id):
        await message.answer("Сначала примите дисклеймер через /start.")
        return
    await send_specialist_menu(message, deps)
