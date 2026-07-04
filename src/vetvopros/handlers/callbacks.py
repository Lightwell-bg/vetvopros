"""Callback: дисклеймер, заглушка оплаты, карточки специалистов и старт чата."""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from vetvopros.bot.deps import BotDeps
from vetvopros.bot.keyboards import back_only_inline, post_answer_main_inline, specialist_start_inline
from vetvopros.bot.tg_utils import chunk_paragraphs, md_to_tg_html
from vetvopros.config.paths import read_texts_file

router = Router(name="callbacks")


@router.callback_query(F.data == "dl:ok")
async def disclaimer_accept(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.from_user is None or query.message is None:
        return
    await state.clear()
    await asyncio.to_thread(deps.users.accept_disclaimer, query.from_user.id)
    body = read_texts_file(deps.settings, "disclaimer_accepted.md")
    parts = chunk_paragraphs(md_to_tg_html(body))
    for i, part in enumerate(parts):
        await query.message.answer(
            part,
            parse_mode="HTML",
            reply_markup=post_answer_main_inline(deps.settings) if i == len(parts) - 1 else None,
        )


@router.callback_query(F.data == "dl:no")
async def disclaimer_decline(query: CallbackQuery, deps: BotDeps) -> None:
    await query.answer()
    if query.message is None:
        return
    short = read_texts_file(deps.settings, "disclaimer_short.md")
    parts = chunk_paragraphs(md_to_tg_html(short))
    for i, part in enumerate(parts):
        await query.message.answer(
            part,
            reply_markup=back_only_inline() if i == len(parts) - 1 else None,
            parse_mode="HTML",
        )


@router.callback_query(F.data == "pay:stub")
async def payment_stub(query: CallbackQuery, deps: BotDeps) -> None:
    await query.answer()
    if query.message is None:
        return
    stub = (
        f"Оплата (заглушка). Провайдер: {deps.settings.payment_provider}.\n"
        "Настройте реального провайдера и вебхук согласно 07_billing_and_limits.md."
    )
    await query.message.answer(stub, reply_markup=back_only_inline())


@router.callback_query(F.data.startswith("spec:info:"))
async def specialist_info(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.message is None or query.data is None:
        return
    await state.clear()
    key = query.data.split(":", 2)[2]
    card = next((c for c in deps.specialist_registry.cards if c.key == key), None)
    if card is None:
        await query.message.answer("Запись не найдена.", reply_markup=back_only_inline())
        return
    lines = [card.display_name, "", "Общение происходит в этом боте: ваши сообщения передаются специалисту, ответы — обратно."]
    if card.note:
        lines.extend(["", card.note])
    lines.extend(
        [
            "",
            "При угрозе жизни обратитесь к местной экстренной службе (112 / 911 и т.п. по стране).",
        ]
    )
    await query.message.answer("\n".join(lines), reply_markup=specialist_start_inline(key))
