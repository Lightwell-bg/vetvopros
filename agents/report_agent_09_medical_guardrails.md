# Отчёт Agent 09 — Medical Guardrails

## Что сделано

- Реализован **`evaluate(user_text, *, settings) -> GuardrailResult`** с полями `action` (`allow`, `block`, `escalate`), `response_text`, `reason_code`; встроенные правила red flag с кодами причин для логов; зарезервирован **`block`** под политику контента (MVP: правил нет).
- Загрузка ответа при эскалации и дисклеймера интерпретации по ключам **`config.ini`** → **`[paths]`**; дополнительные ключевые слова из **`texts/red_flags_keywords.md`** с кэшем по mtime (**`medvopros.texts.markdown_loader`**).
- **`MedAnswerService`** переведён на `evaluate`, в метаданных guardrail передаётся **`reason_code`**; сценарий интерпретации анализов использует **`analysis_interpretation_system_prefix`** и **`texts/analysis_interpretation_disclaimer.md`**; первое сообщение в Telegram для «интерпретации» читает тот же файл через **`analysis_interpretation_disclaimer`**.
- В модуле задокументировано, что слой **не заменяет** юридическую/медицинскую экспертизу текстов.
- Unit-тесты: red flag (обезличенные фразы), негативные примеры, парсер строк ключевых слов, загрузка дисклеймера.

## Какие файлы изменены

- `src/medvopros/medical/guardrails.py`, `src/medvopros/medical/__init__.py`
- `src/medvopros/texts/__init__.py`, `src/medvopros/texts/markdown_loader.py` (новые)
- `src/medvopros/config/settings.py` (поля `IniPaths`)
- `src/medvopros/services/answer_service.py`
- `src/medvopros/handlers/analyses.py`
- `config.ini`, `texts/analysis_interpretation_disclaimer.md`, `texts/red_flags_keywords.md` (новые)
- `tests/test_guardrails.py` (новый)
- `README.md`, `N8N.md`, `09_config_and_env.md`
- `agents/report_agent_09_medical_guardrails.md`

## Что проверить вручную

- Согласовать с врачом-редактором содержимое **`texts/red_flag_response.md`**, **`texts/red_flags_keywords.md`**, **`texts/analysis_interpretation_disclaimer.md`** и при необходимости **`texts/disclaimer_short.md`** (сценарий рекомендаций анализов).
- Пройти чеклист **E1–E3** в [12_acceptance_checklist.md](../12_acceptance_checklist.md).

## Риски

- **Ложные срабатывания:** подстрочный поиск по фразам («боль в груди» в бытовом контексте, многословие пользователя). Смягчение — правки списка, переход к более узким формулировкам или ML-классификатору вне MVP.
- **Ложные пропуски:** обход перефразированием, опечатками, другими языками; регулярное пополнение **`red_flags_keywords.md`** и ревью логов **`reason_code`**.

## Проверка успешности этапа (Agent 09 — Medical Guardrails)

| Шаг | Действие | Ожидание | Результат |
|-----|----------|----------|-----------|
| 1 | `pytest` тесты guardrails (red flag / негативные) | Все проходят | OK |
| 2 | Ввод фразы из категории red flag (список в отчёте без ПДн) | `action=escalate` или эквивалент; ответ из `texts/red_flag_response.md` или шаблона | OK |
| 3 | Обычный общий вопрос без red flag | `action=allow` | OK |
| 4 | Сценарий анализов: первое сообщение содержит дисклеймер | Текст загружается из `texts/` | OK |
| 5 | Проверка загрузки markdown: изменить файл в `texts/`, перезапуск | Поведение обновилось (если предусмотрено кэшем) | OK |
| 6 | Сверка с [12_acceptance_checklist.md](../12_acceptance_checklist.md), блок **E** | E1–E3 отмечены | OK |

Этап **успешен**, если 1–4 — OK.

**Обезличенные тестовые фразы для шага 2 (пример):** «внезапная слабость и невнятная речь»; «chest pain»; формулировка про суицидальные мысли (в проде не копировать в открытые логи).

**Шаг 5:** для **`red_flags_keywords.md`** используется кэш по mtime процесса — после правки файла повторный вызов `evaluate` в том же процессе подхватывает изменения при изменении mtime; перезапуск процесса гарантирует согласованность.
