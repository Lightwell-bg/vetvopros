"""Inline-навигация: главное меню, разделы, перезапуск."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from vetvopros.bot.deps import BotDeps
from vetvopros.bot.keyboards import (
    NAV_ANALYSES,
    NAV_ASK,
    NAV_ASK_LEAVE_ANALYSES,
    NAV_CABINET,
    NAV_HELP,
    NAV_MAIN,
    NAV_RESTART,
    NAV_SPECIALIST,
)
from vetvopros.bot.tg_utils import chunk_paragraphs, md_to_tg_html
from vetvopros.config.paths import read_texts_file
from vetvopros.handlers.menu_content import (
    navigate_main_menu,
    run_restart_callback,
    send_analyses_prompt,
    send_cabinet_with_back,
    send_help_with_back,
    send_specialist_menu,
)

router = Router(name="nav")


async def _send_ask_question_flow(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    if query.message is None or query.from_user is None:
        return
    await state.clear()
    if not deps.users.disclaimer_accepted(query.from_user.id):
        await query.message.answer("Сначала примите условия: /start")
        return
    prompt = read_texts_file(deps.settings, "ask_question_prompt.md")
    for part in chunk_paragraphs(md_to_tg_html(prompt)):
        await query.message.answer(part, parse_mode="HTML")


@router.callback_query(F.data == NAV_MAIN)
async def nav_main(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.message is None or query.from_user is None:
        return
    await state.clear()
    await navigate_main_menu(query.message, deps, query.from_user)


@router.callback_query(F.data == NAV_ASK)
async def nav_ask(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    await _send_ask_question_flow(query, state, deps)


@router.callback_query(F.data == NAV_ASK_LEAVE_ANALYSES)
async def nav_ask_leave_analyses(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """То же, что «Задать вопрос», но явно после сценария «Анализы» (пользователь понимает выход из FSM)."""
    await query.answer()
    await _send_ask_question_flow(query, state, deps)


@router.callback_query(F.data == NAV_HELP)
async def nav_help(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    if query.message is None:
        return
    await state.clear()
    await send_help_with_back(query.message)


@router.callback_query(F.data == NAV_CABINET)
async def nav_cabinet(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.message is None or query.from_user is None:
        return
    await state.clear()
    if not deps.users.disclaimer_accepted(query.from_user.id):
        await query.message.answer("Сначала примите дисклеймер: /start или кнопка «Дисклеймер».")
        return
    await send_cabinet_with_back(
        query.message,
        deps,
        telegram_user_id=query.from_user.id,
        telegram_username=query.from_user.username,
    )


@router.callback_query(F.data == NAV_ANALYSES)
async def nav_analyses(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.message is None or query.from_user is None:
        return
    await state.clear()
    if not deps.settings.features.enable_analyses_flow:
        await query.message.answer("Сценарии анализов отключены в конфигурации.")
        return
    if not deps.users.disclaimer_accepted(query.from_user.id):
        await query.message.answer("Сначала примите дисклеймер: /start.")
        return
    await send_analyses_prompt(query.message)


@router.callback_query(F.data == NAV_SPECIALIST)
async def nav_specialist(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.message is None or query.from_user is None:
        return
    await state.clear()
    if not deps.settings.features.enable_specialist_menu:
        await query.message.answer("Меню специалистов отключено в конфигурации.")
        return
    if not deps.specialist_registry.cards:
        await query.message.answer("Специалисты не заданы в config.ini (секции specialist_*).")
        return
    if not deps.users.disclaimer_accepted(query.from_user.id):
        await query.message.answer("Сначала примите дисклеймер: /start.")
        return
    await send_specialist_menu(query.message, deps)


@router.callback_query(F.data == NAV_RESTART)
async def nav_restart(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await run_restart_callback(query, state, deps)
