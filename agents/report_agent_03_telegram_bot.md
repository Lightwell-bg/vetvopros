# Отчёт Agent 03 — Telegram Bot

## Что сделано

- Реализован запуск **aiogram 3.x**: `src/run_bot.py` → `asyncio.run`, `Bot`, `Dispatcher`, `MemoryStorage` для FSM сценариев анализов, `start_polling`, освобождение пула БД в `finally`.
- Добавлены пакеты **`medvopros/bot/`** (фабрика приложения, middleware зависимостей, клавиатуры, утилита разбиения длинных сообщений) и **`medvopros/handlers/`** (команды, callback, чат, анализы, fallback неизвестных команд).
- Хендлеры **без SQL**: только `asyncio.to_thread` к синхронным репозиториям и сервисам.
- **Дисклеймер**: тексты из `texts/`, inline-кнопки «Принимаю» / «Отказ», запись `disclaimer_accepted_at` через `UserRepository.accept_disclaimer`.
- До принятия дисклеймера обычный текст не уходит в LLM — ответ с просьбой открыть `/start`.
- **`MedAnswerService`**: guardrails (ключевые фразы в `medical/guardrails.py`), биллинг (`SqlBillingService`), вызов OpenAI-compatible **chat** API через **httpx** (синхронно внутри `to_thread`), сохранение сообщений в БД, списание квоты после успешного ответа (`llm`, `analysis_*`).
- Команды/сценарии: `/help`, `/cabinet`, кнопка «Личный кабинет», `/analyses` и FSM при включённом флаге, `/specialist` и callback `spec:*` из секций `[specialist_*]` в `config.ini`.
- **Пост-ответное меню** (`post_answer_main_inline`): «Задать ещё вопрос», «Обратиться к специалисту», «Анализы», «Личный кабинет»; в подразделах — «Главное меню».
- **Релей специалиста:** `handlers/specialist_relay.py`, FSM `SpecialistChatStates`, пересылка в чат специалиста, ответ пациенту только если специалист сделал **reply** на сообщение бота; `RelayRepository` + таблица `specialist_relay_maps` (миграция `002_specialist`); отдельный биллинг `can_send_specialist_message` / `record_specialist_message`; фильтры `ExcludeSpecialistUsersFilter` (ИИ/анализы не для аккаунтов специалистов), подсказка специалисту при обычном тексте без reply.
- **Сброс согласия:** при запуске и остановке `run_bot.py` вызывается `UserRepository.clear_all_disclaimers()`.
- Контракт **`AnswerService.ask` → `AnswerResult`** (`text`, `source`, `metadata`) в `services/protocols.py`.
- **Alembic**: `001_baseline` — `users`, `user_balances`, `messages`; `002_specialist` — `specialist_relay_maps`, поля `specialist_*` в `user_balances`.
- Тексты: `texts/disclaimer_accepted.md`, `ask_question_prompt.md`, `specialist_chat_intro.md`, `specialist_limit_exceeded.md`. В **`.env.example`** — плейсхолдеры вместо секретов.

## Какие файлы изменены / добавлены

- Изменены: `src/run_bot.py`, `src/medvopros/db/models.py`, `src/medvopros/db/__init__.py`, `src/medvopros/services/protocols.py`, `src/medvopros/services/__init__.py`, `.env.example`, `README.md` (ожидается).
- Добавлены: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/001_baseline_users_messages.py`, `alembic/versions/002_specialist_relay_and_billing.py`, `src/medvopros/bot/*`, `src/medvopros/handlers/*`, `src/medvopros/repositories/*`, `src/medvopros/medical/guardrails.py`, `src/medvopros/services/answer_service.py`, `src/medvopros/services/billing_service.py`, `src/medvopros/services/llm_client.py`, `src/medvopros/config/paths.py`, `src/medvopros/config/specialists.py`, `texts/*.md` (в т.ч. постановка вопроса и специалист), `agents/report_agent_03_telegram_bot.md`.

## Что проверить вручную

- Заполнить **`.env`**: `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `LLM_API_KEY`; применить миграции: `alembic upgrade head` из корня репозитория с установленным `DATABASE_URL`.
- Запуск из корня: `python src/run_bot.py`.
- Пройти **C1–C3** и при необходимости **C4** из `12_acceptance_checklist.md` в Telegram с тестовым аккаунтом.
- Убедиться, что модель в `config.ini` (`[llm] chat_model`) доступна вашему API.

## Риски

- **Синхронный SQL** вынесен в `asyncio.to_thread`; при очень высокой нагрузке имеет смысл пул потоков или async-драйвер (этап 2).
- **FSM в памяти** — состояние сценариев анализов теряется при перезапуске процесса.
- **Long polling** — один процесс; масштабирование потребует webhook/очередь.
- **RAG** подключён в `MedAnswerService.ask`: перед LLM выполняется `RagService.retrieve`, при наличии подходящих чанков ответ помечается `source=rag_llm`, а метаданные (`chunk_ids`, `similarities`, `document_slugs`) пишутся в `messages.message_metadata`.
- **Guardrails** — упрощённый список ключевых слов; полноценные правила — в последующих агентах / внешних текстах.

### Проверка успешности этапа (Agent 03 — Telegram Bot)

alembic upgrade head
python src/run_bot.py

| Шаг | Действие | Ожидание | Результат |
|-----|----------|----------|-----------|
| 1 | Запуск бота: `python src/run_bot.py` — процесс с **aiogram** polling не завершается сразу, в логах старт без traceback | Long polling активен | **Не выполнялось в CI** (нужен живой Telegram + PostgreSQL) |
| 2 | `/start` новым пользователем | Показ дисклеймера из `texts/`, кнопки принятия | **Ручная проверка** |
| 3 | До принятия дисклеймера — обычное текстовое сообщение | Ответ не уходит в полный медицинский пайплайн | **OK по коду** (сообщение перенаправляет к `/start`) |
| 4 | Принятие дисклеймера | В БД `disclaimer_accepted_at` заполнен | **Ручная проверка** (SQL или лог) |
| 5 | После принятия — тестовый вопрос | Ответ приходит, нет 500 в логах сервера | **Ручная проверка** |
| 6 | `/help`, личный кабинет (команда/кнопка из ТЗ) | Ожидаемые тексты | **Ручная проверка** |
| 7 | Проверка кода: в `handlers/` нет сырого SQL | Только вызовы сервисов/репозиториев | **OK** |
| 8 | Сверка с `12_acceptance_checklist.md`, блок **C** (C1–C3 минимум) | Отмечено пройдено/не пройдено | **После ручного прогона** |
| 9 | Остановка и снова запуск `python src/run_bot.py`, затем `/start` | Дисклеймер показывается снова | **Ручная проверка** |
| 10 | Два аккаунта: пациент → специалист в `config.ini`; reply специалиста | Текст доходит пациенту | **Ручная проверка** |

Версия клиента/ОС теста: *не зафиксирована (автоматический прогон Telegram в среде агента не выполнялся)*.

Этап считается **готовым к приёмке**, когда шаги **1, 2, 4, 5, 7** подтверждены вручную на стенде заказчика без блокирующих падений.
