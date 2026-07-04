"""Сценарии анализов: FSM + callback выбора режима."""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from vetvopros.bot.deps import BotDeps
from vetvopros.bot.filters import ExcludeSpecialistUsersFilter
from vetvopros.bot.keyboards import (
    ANA_END,
    billing_stub_inline,
    post_answer_after_analyses_flow_inline,
    post_answer_main_inline,
)
from vetvopros.bot.telemetry import forward_qa_event
from vetvopros.bot.tg_utils import chunk_paragraphs, md_to_tg_html, run_with_chat_action
from vetvopros.config.paths import read_texts_file
from vetvopros.vet.guardrails import analysis_interpretation_disclaimer
from vetvopros.services.protocols import AnswerResult

router = Router(name="analyses")
router.message.filter(ExcludeSpecialistUsersFilter())


class AnalysisStates(StatesGroup):
    waiting_suggestion_context = State()
    waiting_interpretation_values = State()


# Многоходовый диалог: после ответа LLM FSM не сбрасываем, иначе следующее сообщение уходит в общий чат.
_FSM_SUG_TRANSCRIPT = "analysis_suggestion_transcript"
_FSM_INT_TRANSCRIPT = "analysis_interpretation_transcript"
_MAX_TRANSCRIPT_CHARS = 12_000


@router.callback_query(F.data == ANA_END)
async def analysis_end_session(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    """Явное завершение сценария «Анализы»: FSM и накопленный транскрипт теряются."""
    await query.answer("Сценарий завершён")
    await state.clear()
    if query.message is None:
        return
    body = read_texts_file(deps.settings, "analysis_flow_ended.md")
    parts = chunk_paragraphs(md_to_tg_html(body))
    for i, part in enumerate(parts):
        await query.message.answer(
            part,
            parse_mode="HTML",
            reply_markup=post_answer_main_inline(deps.settings) if i == len(parts) - 1 else None,
        )


def _append_turn(prior: str, user_text: str, assistant_text: str) -> str:
    block = f"\n\nПользователь: {user_text}\n\nАссистент: {assistant_text}"
    s = (prior or "") + block
    if len(s) <= _MAX_TRANSCRIPT_CHARS:
        return s
    return s[-_MAX_TRANSCRIPT_CHARS:]


@router.callback_query(F.data == "ana:sug")
async def analysis_pick_suggestions(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.from_user is None or query.message is None:
        return
    if not deps.settings.features.enable_analyses_flow:
        await query.message.answer("Сценарий отключён.")
        return
    if not deps.users.disclaimer_accepted(query.from_user.id):
        await query.message.answer("Сначала примите дисклеймер: /start")
        return
    intro = read_texts_file(deps.settings, "disclaimer_short.md")
    for part in chunk_paragraphs(md_to_tg_html(intro)):
        await query.message.answer(part, parse_mode="HTML")
    await state.set_state(AnalysisStates.waiting_suggestion_context)
    await state.update_data({_FSM_SUG_TRANSCRIPT: ""})
    await query.message.answer(
        "Опишите симптомы или ситуацию. Укажите вид животного, возраст, вес и пол, если знаете. "
        "Можно несколькими сообщениями подряд — "
        "бот запомнит контекст, пока вы не нажмёте «Завершить сценарий», не выйдете в другое меню "
        "или не откроете общий вопрос через отдельную кнопку."
    )


@router.callback_query(F.data == "ana:int")
async def analysis_pick_interpretation(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.from_user is None or query.message is None:
        return
    if not deps.settings.features.enable_analyses_flow:
        await query.message.answer("Сценарий отключён.")
        return
    if not deps.users.disclaimer_accepted(query.from_user.id):
        await query.message.answer("Сначала примите дисклеймер: /start")
        return
    intro = analysis_interpretation_disclaimer(deps.settings)
    for part in chunk_paragraphs(md_to_tg_html(intro)):
        await query.message.answer(part, parse_mode="HTML")
    await state.set_state(AnalysisStates.waiting_interpretation_values)
    await state.update_data({_FSM_INT_TRANSCRIPT: ""})
    await query.message.answer(
        "Вставьте показатели и значения анализов вашего питомца. "
        "Укажите вид животного, если ещё не указали. "
        "При необходимости дополняйте ответами на уточнения отдельными сообщениями."
    )


@router.message(AnalysisStates.waiting_suggestion_context, F.text)
async def analysis_suggestion_text(message: Message, state: FSMContext, deps: BotDeps) -> None:
    assert message.from_user is not None
    data = await state.get_data()
    prior = str(data.get(_FSM_SUG_TRANSCRIPT) or "")
    user_line = (message.text or "").strip()
    wait_msg = await message.answer("⏳ Думаю…")
    result = await run_with_chat_action(
        message.bot,
        message.chat.id,
        asyncio.to_thread(
            deps.answer.ask_analysis_suggestions,
            message.from_user.id,
            user_line,
            username=message.from_user.username,
            prior_transcript=prior if prior.strip() else None,
        ),
    )
    await forward_qa_event(
        message.bot,
        deps.settings,
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
        question=user_line,
        answer=result.text,
        source=result.source,
    )
    await _reply_result(message, wait_msg, result, deps)
    if result.source in ("guardrail", "billing_block"):
        await state.clear()
        return
    if result.source == "error":
        return
    await state.update_data(
        {_FSM_SUG_TRANSCRIPT: _append_turn(prior, user_line, result.text)}
    )


@router.message(AnalysisStates.waiting_interpretation_values, F.text)
async def analysis_interpretation_text(message: Message, state: FSMContext, deps: BotDeps) -> None:
    assert message.from_user is not None
    data = await state.get_data()
    prior = str(data.get(_FSM_INT_TRANSCRIPT) or "")
    user_line = (message.text or "").strip()
    wait_msg = await message.answer("⏳ Думаю…")
    result = await run_with_chat_action(
        message.bot,
        message.chat.id,
        asyncio.to_thread(
            deps.answer.ask_analysis_interpretation,
            message.from_user.id,
            user_line,
            username=message.from_user.username,
            prior_transcript=prior if prior.strip() else None,
        ),
    )
    await forward_qa_event(
        message.bot,
        deps.settings,
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
        question=user_line,
        answer=result.text,
        source=result.source,
    )
    await _reply_result(message, wait_msg, result, deps)
    if result.source in ("guardrail", "billing_block"):
        await state.clear()
        return
    if result.source == "error":
        return
    await state.update_data(
        {_FSM_INT_TRANSCRIPT: _append_turn(prior, user_line, result.text)}
    )


async def _reply_result(message: Message, wait_msg: Message, result: AnswerResult, deps: BotDeps) -> None:
    kb = (
        billing_stub_inline()
        if result.source == "billing_block"
        else post_answer_after_analyses_flow_inline(deps.settings)
    )
    parts = chunk_paragraphs(md_to_tg_html(result.text))
    if not parts:
        return
    try:
        await wait_msg.edit_text(
            parts[0],
            reply_markup=kb if len(parts) == 1 else None,
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(parts[0], reply_markup=kb if len(parts) == 1 else None, parse_mode="HTML")
    for i, part in enumerate(parts[1:], start=1):
        await message.answer(part, reply_markup=kb if i == len(parts) - 1 else None, parse_mode="HTML")
