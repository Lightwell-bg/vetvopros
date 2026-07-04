"""Ветеринарные ограничения (MVP): red flags, шаблоны ответов из `texts/`.

Этот программный слой **не заменяет** юридическую и ветеринарную экспертизу пользовательских
текстов и политик продукта — списки ключевых слов и шаблоны должны согласовываться
с ответственным ветеринарным врачом и юристами перед публичным запуском.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vetvopros.config.paths import read_texts_file
from vetvopros.config.settings import Settings
from vetvopros.texts.markdown_loader import load_extra_red_flag_keywords

GuardrailAction = Literal["allow", "block", "escalate"]


@dataclass(frozen=True)
class GuardrailResult:
    """Результат проверки пользовательского текста."""

    action: GuardrailAction
    """allow — обычный пайплайн; escalate — немедленный безопасный ответ (red flag); block — политика (резерв)."""
    response_text: str
    """Текст для пользователя при block/escalate; при allow пустая строка."""
    reason_code: str
    """Код для логов и метаданных; при allow — пустая строка."""


@dataclass(frozen=True)
class _RedFlagRule:
    needle: str
    reason_code: str


# Только реально критичные ветеринарные ситуации.
# Порядок важен: более длинные/специфичные фразы раньше общих.
_BUILTIN_RED_FLAG_RULES: tuple[_RedFlagRule, ...] = (
    # Дыхание и сознание
    _RedFlagRule("не дышит", "red_flag_respiratory"),
    _RedFlagRule("перестал дышать", "red_flag_respiratory"),
    _RedFlagRule("синие дёсны", "red_flag_respiratory"),
    _RedFlagRule("белые дёсны", "red_flag_respiratory"),
    _RedFlagRule("потерял сознание", "red_flag_syncope"),
    _RedFlagRule("потеряла сознание", "red_flag_syncope"),
    _RedFlagRule("без сознания", "red_flag_syncope"),
    _RedFlagRule("не реагирует на прикосновения", "red_flag_syncope"),
    # Судороги
    _RedFlagRule("судороги у кошки", "red_flag_seizure"),
    _RedFlagRule("судороги у собаки", "red_flag_seizure"),
    _RedFlagRule("судороги у кота", "red_flag_seizure"),
    _RedFlagRule("судороги у питомца", "red_flag_seizure"),
    _RedFlagRule("эпилептический приступ", "red_flag_seizure"),
    # Кровотечение
    _RedFlagRule("сильное кровотечение", "red_flag_bleeding"),
    _RedFlagRule("кровотечение не останавливается", "red_flag_bleeding"),
    # Отравления критичные
    _RedFlagRule("отравление антифризом", "red_flag_poisoning"),
    _RedFlagRule("съел антифриз", "red_flag_poisoning"),
    _RedFlagRule("отравление крысиным ядом", "red_flag_poisoning"),
    _RedFlagRule("съел крысиный яд", "red_flag_poisoning"),
    _RedFlagRule("отравление ксилитом", "red_flag_poisoning"),
    _RedFlagRule("съел ксилит", "red_flag_poisoning"),
    _RedFlagRule("кошка съела лилию", "red_flag_poisoning"),
    _RedFlagRule("кот съел лилию", "red_flag_poisoning"),
    # Задержка мочи у кота
    _RedFlagRule("кот не может помочиться", "red_flag_urinary_block"),
    _RedFlagRule("кошка не может помочиться", "red_flag_urinary_block"),
    _RedFlagRule("острая задержка мочи", "red_flag_urinary_block"),
    _RedFlagRule("мочевой пузырь не опорожняется", "red_flag_urinary_block"),
    # Заворот желудка (крупные собаки)
    _RedFlagRule("вздутие живота у собаки", "red_flag_bloat"),
    _RedFlagRule("заворот желудка", "red_flag_bloat"),
    # Тяжёлая травма
    _RedFlagRule("сбила машина", "red_flag_trauma"),
    _RedFlagRule("попал под машину", "red_flag_trauma"),
    _RedFlagRule("упал с большой высоты", "red_flag_trauma"),
    _RedFlagRule("укус ядовитой змеи", "red_flag_snake_bite"),
    _RedFlagRule("укусила змея", "red_flag_snake_bite"),
    # Тепловой удар
    _RedFlagRule("тепловой удар", "red_flag_heatstroke"),
    _RedFlagRule("перегрев животного", "red_flag_heatstroke"),
)

# Зарезервировано под политику контента (MVP: срабатываний нет).
_BLOCK_RULES: tuple[_RedFlagRule, ...] = ()


def _normalized(text: str) -> str:
    return text.casefold()


def _first_match(low: str, rules: tuple[_RedFlagRule, ...]) -> _RedFlagRule | None:
    for rule in rules:
        if rule.needle.casefold() in low:
            return rule
    return None


def _escalation_template(settings: Settings) -> str:
    return read_texts_file(settings, settings.paths.red_flag_response_file).strip()


def evaluate(user_text: str, *, settings: Settings) -> GuardrailResult:
    """Оценить пользовательский ввод и вернуть действие с текстом из шаблонов при необходимости."""
    if not user_text or not user_text.strip():
        return GuardrailResult(action="allow", response_text="", reason_code="")

    low = _normalized(user_text)

    block_hit = _first_match(low, _BLOCK_RULES)
    if block_hit is not None:
        body = _escalation_template(settings)
        return GuardrailResult(action="block", response_text=body, reason_code=block_hit.reason_code)

    hit = _first_match(low, _BUILTIN_RED_FLAG_RULES)
    if hit is None:
        for extra in load_extra_red_flag_keywords(settings):
            if extra.casefold() in low:
                hit = _RedFlagRule(extra, "red_flag_keywords_file")
                break

    if hit is None:
        return GuardrailResult(action="allow", response_text="", reason_code="")

    return GuardrailResult(
        action="escalate",
        response_text=_escalation_template(settings),
        reason_code=hit.reason_code,
    )


def analysis_interpretation_disclaimer(settings: Settings) -> str:
    """Текст дисклеймера сценария «интерпретация анализов» (пользователь и префикс системного промпта)."""
    return read_texts_file(settings, settings.paths.analysis_interpretation_disclaimer_file).strip()


def analysis_interpretation_system_prefix(settings: Settings) -> str:
    """Префикс к системному промпту LLM: дисклеймер + разделитель."""
    return analysis_interpretation_disclaimer(settings) + "\n\n"


def check_red_flags(text: str, *, settings: Settings) -> bool:
    """True, если сработала эскалация по red flags (удобная обёртка для старого кода)."""
    return evaluate(text, settings=settings).action == "escalate"
