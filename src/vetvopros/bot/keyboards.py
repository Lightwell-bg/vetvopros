"""Inline-меню и константы callback_data (навигация)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

from vetvopros.config.settings import Settings
from vetvopros.config.specialists import SpecialistCard

# навигация (короткие значения — лимит Telegram 64 байта)
NAV_MAIN = "nav:main"
NAV_HELP = "nav:help"
NAV_CABINET = "nav:cabinet"
NAV_ANALYSES = "nav:analyses"
NAV_SPECIALIST = "nav:specialist"
NAV_RESTART = "nav:restart"
NAV_ASK = "nav:ask"
# Явный выход из FSM «Анализы» перед общим вопросом (не путать с продолжением сценария)
NAV_ASK_LEAVE_ANALYSES = "nav:ask_leave_analyses"
# Завершить сценарий «Анализы» и сбросить накопленный контекст (FSM + транскрипт)
ANA_END = "ana:end"


def disclaimer_accept_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ознакомился и принимаю", callback_data="dl:ok")],
            [InlineKeyboardButton(text="❌ Отказ", callback_data="dl:no")],
        ]
    )


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def back_to_main_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="🏠 « Главное меню", callback_data=NAV_MAIN)]


def post_answer_main_inline(settings: Settings) -> InlineKeyboardMarkup:
    """После ответа бота (ИИ): основные действия."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="❓ Задать вопрос", callback_data=NAV_ASK)],
        [InlineKeyboardButton(text="🩺 Обратиться к ветеринару-специалисту", callback_data=NAV_SPECIALIST)],
    ]
    if settings.features.enable_analyses_flow:
        rows.append([InlineKeyboardButton(text="🧪 Анализы питомца", callback_data=NAV_ANALYSES)])
    rows.append([InlineKeyboardButton(text="👤 Личный кабинет", callback_data=NAV_CABINET)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def post_answer_after_analyses_flow_inline(settings: Settings) -> InlineKeyboardMarkup:
    """После ответа в сценарии «Анализы»: без кнопки «Задать вопрос», чтобы не сбрасывать FSM случайным нажатием."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🛑 Завершить сценарий (контекст сбросится)",
                callback_data=ANA_END,
            )
        ],
        [InlineKeyboardButton(text="🏠 « Главное меню", callback_data=NAV_MAIN)],
    ]
    if settings.features.enable_analyses_flow:
        rows.append([InlineKeyboardButton(text="🧪 Снова: раздел «Анализы»", callback_data=NAV_ANALYSES)])
    rows.append([InlineKeyboardButton(text="🩺 Обратиться к ветеринару-специалисту", callback_data=NAV_SPECIALIST)])
    rows.append([InlineKeyboardButton(text="👤 Личный кабинет", callback_data=NAV_CABINET)])
    rows.append(
        [
            InlineKeyboardButton(
                text="❓ Общий вопрос боту (выйти из «Анализов»)",
                callback_data=NAV_ASK_LEAVE_ANALYSES,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_inline(settings: Settings, *, disclaimer_accepted: bool) -> InlineKeyboardMarkup:
    """До принятия условий — только справка; после — то же, что пост-ответ (главное меню)."""
    if not disclaimer_accepted:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📄 Условия использования (/start)", callback_data=NAV_MAIN)],
                [InlineKeyboardButton(text="ℹ️ Справка", callback_data=NAV_HELP)],
            ]
        )
    return post_answer_main_inline(settings)


def analyses_choice_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧾 Какие анализы могут быть полезны питомцу", callback_data="ana:sug")],
            [InlineKeyboardButton(text="🔎 Интерпретация показателей анализов", callback_data="ana:int")],
            back_to_main_row(),
        ]
    )


def specialist_list_inline(specialists: list[SpecialistCard]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=c.display_name, callback_data=f"spec:info:{c.key}")] for c in specialists]
    rows.append(back_to_main_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def specialist_start_inline(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Начать общение в боте", callback_data=f"spec:chat:{key}")],
            back_to_main_row(),
        ]
    )


def specialist_session_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Завершить диалог со специалистом", callback_data="spec:end")],
            back_to_main_row(),
        ]
    )


def billing_stub_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплата (заглушка)", callback_data="pay:stub")],
            back_to_main_row(),
        ]
    )


def back_only_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[back_to_main_row()])
