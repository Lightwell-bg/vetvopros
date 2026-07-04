# Отчёт Agent 04 — Database

## Что сделано

- Добавлены модели SQLAlchemy для MVP: `Document`, `DocumentChunk` (поле **Vector** через `pgvector.sqlalchemy`), `SubscriptionPlan`, `Subscription`, `Payment`, `AuditLog`; расширены связи у `User`; композитные индексы для `messages`, `subscriptions`, `audit_log` согласно [03_database_design.md](../03_database_design.md).
- Константа размерности эмбеддингов: `src/medvopros/db/constants.py` (**1536**, синхронно с `config.ini` `[rag] embedding_dimensions`).
- Миграция **`003_rag_audit`**: `CREATE EXTENSION IF NOT EXISTS vector`, таблицы RAG/биллинга/аудита, уникальность `(document_id, chunk_index)`, индексы по дизайну, **HNSW** на `embedding` с `vector_cosine_ops` и параметрами `m=16`, `ef_construction=64` + комментарий в файле миграции о пересоздании после наполнения; замена индекса `messages` на `(user_id, created_at DESC)`.
- Репозитории: `DocumentRepository`, `ChunkRepository` (в т.ч. `search_similar` по cosine distance), `BillingRepository`, `AuditRepository`; у `MessageRepository` добавлен `list_for_user`; экспорт всех репозиториев из `repositories/__init__.py`.
- Регистрация типа vector для **psycopg3** при создании движка в `session.py`.
- Интеграционный тест `tests/test_repositories_db.py` (pytest), конфигурация маркеров в `pyproject.toml`.

## Какие файлы изменены / добавлены

- `src/medvopros/db/constants.py` (новый)
- `src/medvopros/db/models.py`, `src/medvopros/db/__init__.py`, `src/medvopros/db/session.py`
- `alembic/versions/003_rag_vector_audit_billing.py` (новый)
- `src/medvopros/repositories/document_repo.py`, `chunk_repo.py`, `billing_repo.py`, `audit_repo.py` (новые)
- `src/medvopros/repositories/message_repo.py`, `__init__.py`
- `tests/conftest.py`, `tests/test_repositories_db.py` (новые)
- `pyproject.toml` — `[tool.pytest.ini_options]`
- `README.md`
- `agents/report_agent_04_database.md` (этот файл)

## Что проверить вручную

- Версия **PostgreSQL** и наличие пакета **pgvector** в кластере (расширение `vector` создаётся миграцией; нужны права суперпользователя или предварительно установленное расширение по политике хостинга).
- После `alembic upgrade head`: `SELECT extname FROM pg_extension WHERE extname = 'vector';` — строка `vector`.
- Список таблиц включает `users`, `messages`, `documents`, `document_chunks`, `user_balances`, `specialist_relay_maps`, `subscription_plans`, `subscriptions`, `payments`, `audit_log`.
- Согласованность **`embedding_dimensions`** в `config.ini` с типом `vector(N)` в БД (и с `EMBEDDING_DIMENSIONS` в коде).

## Риски

- Смена размерности эмбеддингов требует новой миграции (изменение типа столбца / пересоздание индекса) и полного пересчёта векторов.
- Параметры **HNSW** на пустой БД консервативны; на большом объёме данных имеет смысл пересоздать индекс с иными `m` / `ef_construction` и выполнить `ANALYZE`.

---

## Проверка успешности этапа (Agent 04 — Database)

| Шаг | Действие | Ожидание | Результат |
|-----|----------|----------|-----------|
| 1 | Чистая БД (или тестовая), корректный `DATABASE_URL` | Подключение с хоста разработки | OK |
| 2 | `alembic upgrade head` из корня проекта | Миграции без ошибок | OK |
| 3 | `alembic current` | Хэш ревизии совпадает с head | OK — вывод: **`003_rag_audit (head)`** |
| 4 | `SELECT extname FROM pg_extension WHERE extname = 'vector';` | Строка `vector` | OK *(проверено применением миграции 003 на dev-БД)* |
| 5 | Список таблиц по [03_database_design.md](../03_database_design.md) | Все таблицы MVP созданы | OK |
| 6 | Колонка эмбеддинга: тип `vector(1536)` и `config.ini` `embedding_dimensions` | Соответствие | OK |
| 7 | `pytest tests/test_repositories_db.py -v` | Зелёные тесты | OK |
| 8 | Минимальный CRUD через репозиторий | Создание/чтение без ошибки | OK *(покрыто интеграционным тестом)* |

Этап **успешен** (шаги 2–6 — OK).

**Примечание:** в логи и отчёты не включать DSN с паролем.
