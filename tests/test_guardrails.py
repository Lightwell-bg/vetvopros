"""Тесты ветеринарных guardrails (red flags, шаблоны из texts/)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vetvopros.config.settings import load_settings
from vetvopros.vet.guardrails import (
    analysis_interpretation_disclaimer,
    analysis_interpretation_system_prefix,
    evaluate,
)
from vetvopros.texts.markdown_loader import parse_keyword_lines

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings():
    return load_settings(config_ini=str(_REPO_ROOT / "config.ini"))


@pytest.mark.parametrize(
    "phrase,expected_code",
    [
        ("кот не может помочиться уже 6 часов", "red_flag_urinary_block"),
        ("питомец не дышит и синие дёсны", "red_flag_respiratory"),
        ("судороги у кошки продолжаются несколько минут", "red_flag_seizure"),
        ("отравление антифризом у собаки", "red_flag_poisoning"),
        ("вздутие живота у собаки с одышкой", "red_flag_bloat"),
        ("сбила машина нашего кота", "red_flag_trauma"),
        ("тепловой удар у собаки", "red_flag_heatstroke"),
        ("сильное кровотечение у кошки не останавливается", "red_flag_bleeding"),
        ("укусила змея нашу кошку", "red_flag_snake_bite"),
        ("острая задержка мочи у кота", "red_flag_urinary_block"),
    ],
)
def test_evaluate_red_flag_escalate(settings, phrase: str, expected_code: str) -> None:
    r = evaluate(phrase, settings=settings)
    assert r.action == "escalate"
    assert r.reason_code == expected_code
    assert "ветклинику" in r.response_text.casefold() or "ветеринар" in r.response_text.casefold()


def test_evaluate_allow_benign(settings) -> None:
    r = evaluate("Кошка чихнула один раз, что это может быть?", settings=settings)
    assert r.action == "allow"
    assert r.response_text == ""
    assert r.reason_code == ""


def test_evaluate_allow_benign_dog(settings) -> None:
    r = evaluate("Собака плохо ест второй день, надо ли волноваться?", settings=settings)
    assert r.action == "allow"


def test_evaluate_allow_chocolate_human_no_false_positive(settings) -> None:
    """Обычный вопрос о шоколаде без признаков критического отравления не должен быть red flag."""
    r = evaluate("Можно ли собаке немного шоколада?", settings=settings)
    assert r.action == "allow"


def test_extra_keywords_from_file(monkeypatch, settings) -> None:
    monkeypatch.setattr(
        "vetvopros.vet.guardrails.load_extra_red_flag_keywords",
        lambda _s: ("уникальный_маркер_теста_редфлага",),
    )
    r = evaluate("просто текст с уникальный_маркер_теста_редфлага внутри", settings=settings)
    assert r.action == "escalate"
    assert r.reason_code == "red_flag_keywords_file"


def test_parse_keyword_lines() -> None:
    raw = "# c\n\nalpha\n  beta  \n# skip\n"
    assert parse_keyword_lines(raw) == ("alpha", "beta")


def test_analysis_disclaimer_loads_from_texts(settings) -> None:
    text = analysis_interpretation_disclaimer(settings)
    assert "лабораторных" in text.casefold()
    assert analysis_interpretation_system_prefix(settings).startswith(text)
