"""Обычные текстовые сообщения (после принятия дисклеймера)."""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from vetvopros.bot.deps import BotDeps
from vetvopros.bot.filters import ExcludeSpecialistUsersFilter
from vetvopros.bot.keyboards import billing_stub_inline, post_answer_main_inline
from vetvopros.bot.tg_utils import chunk_paragraphs, md_to_tg_html, run_with_chat_action
from vetvopros.bot.telemetry import forward_qa_event
from vetvopros.services.protocols import AnswerResult

router = Router(name="chat")
router.message.filter(ExcludeSpecialistUsersFilter())


@router.message(F.text, StateFilter(None), ~F.text.startswith("/"))
async def on_user_text(message: Message, deps: BotDeps) -> None:
    if message.from_user is None:
        return
    if not deps.users.disclaimer_accepted(message.from_user.id):
        await message.answer("Чтобы продолжить, примите дисклеймер: команда /start.")
        return
    wait_msg = await message.answer("⏳ Думаю…")
    result: AnswerResult = await run_with_chat_action(
        message.bot,
        message.chat.id,
        asyncio.to_thread(
            deps.answer.ask,
            message.from_user.id,
            message.text or "",
            username=message.from_user.username,
        ),
    )
    await forward_qa_event(
        message.bot,
        deps.settings,
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
        question=message.text or "",
        answer=result.text,
        source=result.source,
    )
    kb = (
        billing_stub_inline()
        if result.source == "billing_block"
        else post_answer_main_inline(deps.settings)
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
