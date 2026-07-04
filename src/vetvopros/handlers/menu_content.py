"""Отправка текстов разделов, стартового экрана и перезапуска."""

from __future__ import annotations

import asyncio

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from vetvopros.bot.deps import BotDeps
from vetvopros.bot.keyboards import (
    analyses_choice_inline,
    back_only_inline,
    disclaimer_accept_inline,
    main_menu_inline,
    post_answer_main_inline,
    remove_reply_keyboard,
    specialist_list_inline,
)
from vetvopros.bot.messages import HELP_MESSAGE
from vetvopros.bot.tg_utils import chunk_paragraphs, md_to_tg_html
from vetvopros.config.paths import read_texts_file
from vetvopros.bot.telemetry import forward_start_event


async def send_disclaimer_welcome(message: Message, deps: BotDeps) -> None:
    """Текст welcome дисклеймера + кнопки принятия (без телеметрии /start)."""
    welcome = read_texts_file(deps.settings, "disclaimer_welcome.md")
    kb = disclaimer_accept_inline()
    parts = chunk_paragraphs(md_to_tg_html(welcome))
    for i, part in enumerate(parts):
        await message.answer(
            part,
            reply_markup=kb if i == len(parts) - 1 else None,
            parse_mode="HTML",
        )


async def navigate_main_menu(message: Message, deps: BotDeps, from_user: User) -> None:
    """Кнопка «Главное меню» и аналог: не дублировать команду /start и не слать групповую телеметрию старта."""
    await asyncio.to_thread(deps.users.get_or_create, from_user.id, from_user.username)
    if deps.users.disclaimer_accepted(from_user.id):
        await message.answer("Меню:", reply_markup=post_answer_main_inline(deps.settings))
        return
    await send_disclaimer_welcome(message, deps)


async def present_start_flow(message: Message, deps: BotDeps, from_user: User) -> None:
    await asyncio.to_thread(deps.users.get_or_create, from_user.id, from_user.username)
    await forward_start_event(
        message.bot,
        deps.settings,
        user_id=from_user.id,
        full_name=from_user.full_name,
        username=from_user.username,
    )
    if deps.users.disclaimer_accepted(from_user.id):
        await message.answer("Меню:", reply_markup=post_answer_main_inline(deps.settings))
        return
    await send_disclaimer_welcome(message, deps)


async def send_help_with_back(message: Message) -> None:
    parts = chunk_paragraphs(md_to_tg_html(HELP_MESSAGE))
    kb = back_only_inline()
    for i, part in enumerate(parts):
        await message.answer(part, reply_markup=kb if i == len(parts) - 1 else None, parse_mode="HTML")


def _iso_date_to_dmY(iso: str | None) -> str | None:
    if not iso or len(iso) < 10:
        return None
    try:
        y, m, d = iso[:10].split("-")
        return f"{int(d):02d}.{int(m):02d}.{y}"
    except (ValueError, TypeError):
        return None


def _pack_usage_line(*, used: int, capacity: int) -> str:
    if capacity <= 0:
        return "не приобретён"
    return f"{used} из {capacity} использовано"


async def send_cabinet_with_back(
    message: Message,
    deps: BotDeps,
    *,
    telegram_user_id: int | None = None,
    telegram_username: str | None = None,
) -> None:
    """Кабинет по лимитам. Для открытия по inline-кнопке передайте ``telegram_user_id`` = того, кто нажал
    (``query.from_user``): у ``query.message.from_user`` в личке с ботом часто указан **бот**, не пациент."""
    if telegram_user_id is not None:
        tid, tun = telegram_user_id, telegram_username
    else:
        assert message.from_user is not None
        tid, tun = message.from_user.id, message.from_user.username
    await asyncio.to_thread(deps.users.get_or_create, tid, tun)
    snap = await asyncio.to_thread(deps.billing.get_cabinet_snapshot, tid)
    admin_note = ""
    if snap.billing_bypass_admin:
        admin_note = (
            "🛡️ **Режим администратора** (`admin_ids`): лимиты не списываются.\n\n"
        )
    if snap.subscription_active and snap.subscription_until_iso:
        sub_dm = _iso_date_to_dmY(snap.subscription_until_iso)
        sub_bits = [f"📅 **Подписка** до **{sub_dm}**"]
        if snap.subscription_ai_unlimited:
            sub_bits.append("🤖 по подписке: **безлимит** запросов к ассистенту")
        elif (
            snap.subscription_finite_ai_quota is not None
            and int(snap.subscription_finite_ai_quota) > 0
            and snap.subscription_finite_ai_used is not None
        ):
            sub_bits.append(
                "🤖 по подписке к ассистенту: "
                f"**{snap.subscription_finite_ai_used}** из **{snap.subscription_finite_ai_quota}** "
                "за период использовано"
            )
        if snap.subscription_specialist_cap > 0:
            sub_bits.append(
                "🩺 по подписке к ветеринару-специалисту: "
                f"**{snap.subscription_specialist_used}** из **{snap.subscription_specialist_cap}** "
                "ед. за период использовано"
            )
        sub_block = "\n".join(sub_bits)
    else:
        sub_block = "📅 **Подписка:** не оформлена"

    ai_pack_txt = _pack_usage_line(
        used=snap.ai_pack_answers_used,
        capacity=snap.ai_pack_answers_capacity,
    )
    sp_pack_txt = _pack_usage_line(
        used=snap.specialist_pack_units_used,
        capacity=snap.specialist_pack_units_capacity,
    )

    text = (
        "🗂️ **Личный кабинет**\n\n"
        f"{admin_note}"
        f"🤖 Бесплатных запросов к ассистенту: **{snap.free_used}** из **{snap.free_limit}** использовано\n\n"
        f"🩺 Бесплатных запросов к ветеринару-специалисту: **{snap.specialist_free_used}** из **{snap.specialist_free_limit}** использовано\n\n"
        f"{sub_block}\n\n"
        "📦 **Дополнительный пакет** (купленный):\n"
        f"• 🤖 к ассистенту — {ai_pack_txt}\n"
        f"• 🩺 к ветеринару-специалисту — {sp_pack_txt}\n\n"
        "💳 Оплата: заглушка (см. документацию проекта / настройки провайдера)."
    )
    parts = chunk_paragraphs(md_to_tg_html(text))
    kb = back_only_inline()
    for i, part in enumerate(parts):
        await message.answer(part, reply_markup=kb if i == len(parts) - 1 else None, parse_mode="HTML")


async def send_analyses_prompt(message: Message) -> None:
    await message.answer("Выберите сценарий:", reply_markup=analyses_choice_inline())


async def send_specialist_menu(message: Message, deps: BotDeps) -> None:
    await message.answer(
        "Выберите ветеринарного специалиста. Диалог ведётся в этом боте; за сообщения специалисту действует отдельная квота.",
        reply_markup=specialist_list_inline(deps.specialist_registry.cards),
    )


async def run_restart(message: Message, state: FSMContext, deps: BotDeps) -> None:
    await state.clear()
    if message.from_user is None:
        return
    await asyncio.to_thread(deps.users.get_or_create, message.from_user.id, message.from_user.username)
    dac = deps.users.disclaimer_accepted(message.from_user.id)
    await message.answer(
        "Сценарий сброшен (в т.ч. шаги «Анализов»).",
        reply_markup=remove_reply_keyboard(),
    )
    await message.answer(
        "Меню:",
        reply_markup=main_menu_inline(deps.settings, disclaimer_accepted=dac),
    )


async def run_restart_callback(query: CallbackQuery, state: FSMContext, deps: BotDeps) -> None:
    await state.clear()
    await query.answer("Сброс выполнен")
    m = query.message
    if m is None or query.from_user is None:
        return
    await asyncio.to_thread(deps.users.get_or_create, query.from_user.id, query.from_user.username)
    dac = deps.users.disclaimer_accepted(query.from_user.id)
    await m.answer(
        "Сценарий сброшен.",
        reply_markup=remove_reply_keyboard(),
    )
    await m.answer(
        "Меню:",
        reply_markup=main_menu_inline(deps.settings, disclaimer_accepted=dac),
    )
