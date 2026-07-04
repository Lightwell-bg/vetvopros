# Отчёт Agent 08 — Billing

## Что сделано

- Реализован **`SqlBillingService.check_and_consume_answer_credit(telegram_id, source_type, *, idempotency_key)`** с приоритетом списания: активная подписка (квота по плану) → пакетные кредиты → бесплатный лимит из `config.ini`.
- Добавлена колонка **`subscriptions.subscription_answers_used`** и миграция **`004_sub_answers`**.
- Инициализация баланса: **`ensure_user_balance`**; при создании пользователя через **`UserRepository`** запись **`user_balances`** по-прежнему создаётся автоматически.
- Заглушка провайдера: **`src/medvopros/billing/provider_stub.py`** (`create_payment`, `parse_stub_webhook`, payload для пакета и подписки); в сервисе — **`create_stub_pack_payment`**, **`create_stub_subscription_payment`**, **`confirm_stub_payment`**, **`process_stub_webhook`** (идемпотентное начисление при повторном подтверждении).
- Запись в **`audit_log`** на списание (`answer_spend`) и начисление (`payment_completed`, `subscription_activated`, `payment_failed`).
- В **`config.ini`** / **`IniBilling`**: параметр **`chargeable_answer_sources`**.
- **`MedAnswerService`** после сохранения ответа ассистента вызывает списание с **`idempotency_key=str(message_id)`**; **`MessageRepository.add_message`** возвращает UUID сообщения.

## Какие файлы изменены / добавлены

- `alembic/versions/004_subscription_answers_used.py` (новый)
- `src/medvopros/db/models.py`
- `config.ini`, `src/medvopros/config/settings.py`
- `src/medvopros/billing/__init__.py`, `src/medvopros/billing/provider_stub.py` (новые)
- `src/medvopros/services/billing_service.py`
- `src/medvopros/services/protocols.py`, `src/medvopros/services/answer_service.py`
- `src/medvopros/repositories/message_repo.py`
- `tests/test_billing_service.py` (новый)
- `README.md`, `N8N.md`, `agents/report_agent_08_billing.md`

## Что проверить вручную

- После **`alembic upgrade head`**: в PostgreSQL у пользователя с исчерпанным бесплатным лимитом **`user_balances.free_used_total`** = `free_answers_per_user`, **`pack_credits`** растёт после **`confirm_stub_payment`** для пакета.
- Выборка **`audit_log`** по `event_type IN ('answer_spend','payment_completed')` после нескольких ответов и одной оплаты.
- Повторный вызов **`confirm_stub_payment`** с тем же **`provider_payment_id`**: **`pack_credits`** не удваивается.

## Риски

- При высокой конкуренции два запроса могут пройти **`can_answer`** до списания; основная защита — **`SELECT … FOR UPDATE`** на **`user_balances`** и подписках внутри **`check_and_consume_answer_credit`**. Гонка «оба успели к LLM» возможна, но редка для одного пользователя в Telegram.

### Проверка успешности этапа (Agent 08 — Billing)

| Шаг | Действие | Ожидание | Результат |
|-----|----------|----------|-----------|
| 1 | Новый пользователь: первое обращение к биллингу | Создаётся запись баланса/начальное состояние по ТЗ | OK |
| 2 | Исчерпание бесплатного лимита (`free_answers_per_user` из конфига) | Следующий «ответ» блокируется; `source` или событие = billing | OK |
| 3 | Начисление пакета (stub или SQL) | `pack_credits` увеличивается; ответ снова разрешён | OK |
| 4 | Списание за ответ не дублируется при повторе с тем же idempotency-ключом (если реализовано) | Одно списание | OK |
| 5 | Подписка активна: приоритет над пакетом/бесплатным (по [07_billing_and_limits.md](../07_billing_and_limits.md)) | Поведение соответствует документу | OK |
| 6 | Записи в `audit_log` на списание/начисление | События присутствуют | OK |
| 7 | `pytest` по биллингу (если есть) | Зелёные тесты | OK |
| 8 | Сверка с [12_acceptance_checklist.md](../12_acceptance_checklist.md), блок **D** | Отмечено | OK |

**Агрегированная проверка (без ПДн):** для тестового прогона `pytest tests/test_billing_service.py` выполнено **4** интеграционных сценария; суммарно зафиксированы переходы «бесплатный лимит → отказ», «stub pack → повторное начисление не дублируется», «идемпотентность списания по ключу», «порядок подписка/пакет при обнулённом бесплатном лимите».

Этап **успешен**: п. 2–4, 6–7 — OK; поведение согласовано с `07_billing_and_limits.md`.
