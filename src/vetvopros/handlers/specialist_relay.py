"""Релей: пациент ↔ специалист в одном боте; ответ специалиста только через reply."""

from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from vetvopros.bot.deps import BotDeps
from vetvopros.bot.filters import SpecialistIdentityFilter, SpecialistReplyFilter
from vetvopros.bot.keyboards import (
    NAV_SPECIALIST,
    post_answer_main_inline,
    specialist_session_inline,
)
from vetvopros.bot.tg_utils import chunk_paragraphs, md_to_tg_html
from vetvopros.config.paths import read_texts_file

router = Router(name="specialist_relay")


class SpecialistChatStates(StatesGroup):
    in_session = State()


@router.message(
    SpecialistIdentityFilter(),
    F.text,
    ~F.text.startswith("/"),
    ~F.reply_to_message,
)
async def specialist_reply_hint(message: Message) -> None:
    await message.answer(
        "Чтобы ответить пациенту, нажмите «Ответить» на сообщение бота с текстом от пациента.",
    )


@router.message(SpecialistReplyFilter(), F.reply_to_message)
async def specialist_incoming_reply(message: Message, deps: BotDeps) -> None:
    assert message.from_user is not None and message.reply_to_message is not None
    patient_id = await asyncio.to_thread(
        lambda: deps.relay.find_patient_for_reply(
            specialist_chat_id=message.chat.id,
            reply_to_message_id=message.reply_to_message.message_id,
        ),
    )
    if patient_id is None:
        return
    body = message.text or message.caption or "(вложение — откройте в Telegram)"
    text = f"Сообщение специалиста:\n{body}"
    for part in chunk_text(text):
        await message.bot.send_message(patient_id, part)


@router.callback_query(F.data.startswith("spec:chat:"))
async def specialist_start_chat(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    if query.from_user is None or query.message is None or query.data is None:
        return
    if not deps.settings.features.enable_specialist_menu:
        await query.message.answer("Раздел отключён в конфигурации.")
        return
    if not deps.users.disclaimer_accepted(query.from_user.id):
        await query.message.answer("Сначала примите условия: /start")
        return
    key = query.data.split(":", 2)[2]
    stid = await deps.specialist_registry.telegram_id_for(query.bot, key)
    if stid is None:
        await query.message.answer(
            "Не удалось определить Telegram специалиста. "
            "Задайте telegram_user_id или telegram_username в config.ini.",
        )
        return
    if stid == query.from_user.id:
        await query.message.answer("Нельзя открыть диалог с самим собой.")
        return
    if not await asyncio.to_thread(deps.billing.can_send_specialist_message, query.from_user.id):
        lim = read_texts_file(deps.settings, "specialist_limit_exceeded.md")
        parts = chunk_paragraphs(md_to_tg_html(lim))
        for i, part in enumerate(parts):
            await query.message.answer(
                part,
                reply_markup=post_answer_main_inline(deps.settings) if i == len(parts) - 1 else None,
                parse_mode="HTML",
            )
        return
    await state.set_state(SpecialistChatStates.in_session)
    await state.update_data(specialist_key=key, specialist_telegram_id=stid)
    intro = read_texts_file(deps.settings, "specialist_chat_intro.md")
    for part in chunk_paragraphs(md_to_tg_html(intro)):
        await query.message.answer(part, parse_mode="HTML")
    await query.message.answer(
        "Напишите сообщение специалисту. Ответ придёт здесь, когда специалист ответит **ответом (reply)** "
        "на сообщение бота в своём чате с ботом.",
        reply_markup=specialist_session_inline(),
    )


@router.callback_query(F.data == "spec:end", StateFilter(SpecialistChatStates.in_session))
async def specialist_end_callback(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer("Диалог завершён")
    await state.clear()
    if query.message:
        await query.message.answer(
            "Диалог со специалистом завершён.",
            reply_markup=post_answer_main_inline(deps.settings),
        )


@router.message(Command("cancel"), SpecialistChatStates.in_session)
async def specialist_cancel_cmd(message: Message, state: FSMContext, deps: BotDeps) -> None:
    await state.clear()
    await message.answer("Диалог со специалистом завершён.", reply_markup=post_answer_main_inline(deps.settings))


@router.message(SpecialistChatStates.in_session, F.text)
async def patient_to_specialist_text(message: Message, state: FSMContext, deps: BotDeps) -> None:
    if message.text and message.text.startswith("/"):
        return
    assert message.from_user is not None
    data = await state.get_data()
    stid = data.get("specialist_telegram_id")
    skey = data.get("specialist_key", "")
    if not isinstance(stid, int):
        await state.clear()
        await message.answer("Сессия сброшена. Выберите специалиста снова.", reply_markup=post_answer_main_inline(deps.settings))
        return
    if not await asyncio.to_thread(deps.billing.can_send_specialist_message, message.from_user.id):
        lim = read_texts_file(deps.settings, "specialist_limit_exceeded.md")
        parts = chunk_paragraphs(md_to_tg_html(lim))
        for i, part in enumerate(parts):
            await message.answer(
                part,
                reply_markup=specialist_session_inline() if i == len(parts) - 1 else None,
                parse_mode="HTML",
            )
        return
    un = message.from_user.username or "—"
    line = f"Сообщение от пациента (id {message.from_user.id}, @{un}):\n{message.text}"
    try:
        sent = await message.bot.send_message(stid, line)
    except Exception:
        await message.answer(
            "Не удалось доставить сообщение специалисту. Возможно, специалист ещё не нажал /start у этого бота.",
            reply_markup=specialist_session_inline(),
        )
        return
    await asyncio.to_thread(deps.billing.record_specialist_message, message.from_user.id)
    await asyncio.to_thread(
        lambda: deps.relay.save_bridge(
            specialist_chat_id=sent.chat.id,
            bridge_message_id=sent.message_id,
            patient_telegram_id=message.from_user.id,
            specialist_key=str(skey),
        ),
    )
    await message.answer("Сообщение отправлено специалисту.", reply_markup=specialist_session_inline())


# Повторный выбор «Обратиться к специалисту» из меню во время сессии — сброс и новый выбор
@router.callback_query(F.data == NAV_SPECIALIST, StateFilter(SpecialistChatStates.in_session))
async def specialist_nav_while_in_session(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await query.answer()
    await state.clear()
    from vetvopros.handlers.menu_content import send_specialist_menu

    if query.message is None or query.from_user is None:
        return
    await send_specialist_menu(query.message, deps)
