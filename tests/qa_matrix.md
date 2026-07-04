# Матрица тест-кейсов (QA ↔ 12_acceptance_checklist)

Связь с [12_acceptance_checklist.md](../12_acceptance_checklist.md). Статусы: **pass** (подтверждено автотестом или ручным прогоном), **fail** (дефект), **skip** (не выполнялось / вне среды).

| ID | Чеклист | Шаги | Ожидаемый результат | Авто / ручное | Статус |
|----|---------|------|----------------------|---------------|--------|
| QA-A1 | A1 | Запуск без обязательных переменных `.env`; затем с полным `.env` | Без секретов — понятная ошибка; со всеми — приложение стартует | Ручное | skip |
| QA-A2 | A2 | Изменить `prompts/system_prompt.md`, перезапустить бота, задать вопрос | Стиль/содержание ответа отражают новый системный промпт | Ручное | skip |
| QA-A3 | A3 | `alembic upgrade head`, открыть `/status` в админке | БД и pgvector в статусе OK | Ручное | skip |
| QA-B1 | B1 | Админка: черновик → правка → publish | Документ в нужном статусе, при `auto_index_on_publish` — индексация | Ручное | skip |
| QA-B2 | B2 | После индексации опубликованного документа | В `document_chunks` есть строки с embedding | Ручное / интегр. БД | skip |
| QA-B3 | B3 | Вопрос по содержимому базы | В логах/metadata ответа есть chunk ids и scores (после интеграции RAG в диалог) | Ручное | skip |
| QA-B4 | B4 | Вопрос вне базы (низкая схожесть) | `source` ответа ассистента содержит сценарий `llm` / `rag+llm` по политике; fallback без «молчания» | Ручное | **fail** — см. отчёт Agent 10 |
| QA-B5 | B5 | Unpublish документа | Чанки удалены или не участвуют в поиске | Ручное | skip |
| QA-C1 | C1 | Новый пользователь: `/start` | Показан дисклеймер из `texts/` | Ручное | skip |
| QA-C2 | C2 | Не приняв дисклеймер, отправить вопрос | Перенаправление к принятию, без LLM-ответа на вопрос | Ручное | skip |
| QA-C3 | C3 | После «Принимаю» — текстовый вопрос | Получен ответ ассистента | Ручное | skip |
| QA-C4 | C4 | `/help`, личный кабинет | Ожидаемые тексты и меню | Ручное | skip |
| QA-C5 | C5 | Смоделировать сбой LLM | Пользователь видит текст из `error_generic.md`, без stack trace | Авто: `test_ask_llm_error_user_friendly_no_stack_in_result` | pass |
| QA-D1 | D1 | Исчерпать бесплатный лимит | Сообщение о лимите; дальше — только после оплаты/пакета | Авто+ручное: `test_billing_free_limit_and_pack` (интегр.) | pass\* |
| QA-D2 | D2 | Guardrail / billing_block | Списание не начисляется за ответы с `source` guardrail/billing_block | Авто: `test_chargeable_sources_exclude_guardrail_and_block`, `test_ask_red_flag_no_llm_no_billing_consume`, `test_ask_billing_block_no_llm_no_consume` | pass |
| QA-D3 | D3 | Stub-платёж, confirm | `pack_credits` увеличиваются, ответы снова доступны | Авто: `test_billing_free_limit_and_pack` (интегр.) | pass\* |
| QA-D4 | D4 | Списания и платежи | В `audit_log` есть `answer_spend`, `payment_completed` при сценариях | Ручное / интегр. | skip |
| QA-E1 | E1 | Red flag фраза | Эскалация, шаблон из guardrails, без вызова LLM | Авто: `test_evaluate_red_flag_escalate`, `test_ask_red_flag_no_llm_no_billing_consume` | pass |
| QA-E2 | E2 | Выборка ответов на «диагноз» | Нет категоричного диагноза (политика промптов) | Ручное | skip |
| QA-E3 | E3 | Сценарий интерпретации анализов | Первое сообщение / префикс с дисклеймером при включённом флаге | Авто: `test_analysis_disclaimer_loads_from_texts` | pass |
| QA-F1 | F1 | Секция специалиста в `config.ini` | Кнопка/меню по конфигу после перезапуска | Ручное | skip |
| QA-F2 | F2 | Контакт специалиста | Текст с оговоркой сервиса | Ручное | skip |
| QA-G1 | G1 | Логин в админку | Неверный пароль отклонён | Ручное | skip |
| QA-G2 | G2 | Индексация из UI | Job стартует, статус обновляется | Ручное | skip |
| QA-G3 | G3 | `/audit` | Видны последние события | Ручное | skip |
| QA-H1 | H1 | Выборка `messages` | У ответов ассистента заполнен `source` | Ручное / SQL | skip |
| QA-H2 | H2 | Критичные события | Записи в `audit_log` | Ручное | skip |
| QA-RAG-TH | B4/B3 | Юнит: порог similarity, max_context | Ниже порога отфильтровано; лимит чанков соблюдён | Авто: `test_retrieve_respects_threshold_and_max_context` | pass |
| QA-RAG-EMB | B3 | Ошибка API эмбеддингов | Пустой retrieve без падения процесса | Авто: `test_retrieve_embedding_error_returns_empty` | pass |
| QA-ORCH-RAG | B4 | `MedAnswerService.ask` | На успешном пути вызывается `rag.retrieve`; без попаданий — `source=llm`, со справочником — `source=rag_llm` | Авто: `test_ask_benign_llm_calls_consume_when_rag_empty` (+ интеграционные при `DATABASE_URL`) | pass |

\*Интеграционные тесты: `pytest -m integration` при заданном `DATABASE_URL` в `.env`.

## Дефекты (сводка)

| ID | Приоритет | Описание | Владелец |
|----|-----------|----------|----------|
| ~~DEF-RAG-01~~ | (закрыто) | RAG подключён к `MedAnswerService.ask()` (`rag.retrieve`, при попаданиях — `rag_llm`). | — |
| DEF-CHK | — | Секции A–H чеклиста требуют полного ручного прогона в стендовой среде. | QA |

Автотесты обновлены: на успешном пути мок ожидает вызов `rag.retrieve`; при отсутствии чанков — тарификация `llm`.
