# Отчёт Agent 05 — RAG

## Что сделано

- Реализованы модули `rag/chunking.py`, `rag/embeddings.py`, `rag/ingest.py`, `rag/search.py` и сервис `RagService` с `retrieve(query) -> list[ChunkHit]` (score, id, slug, контент), `message_metadata` для логирования в духе `04_rag_design.md`, `reindex_document` и `reindex_all_published`.
- Векторный поиск в `ChunkRepository.search_similar` ограничен документами со статусом **`published`**; при снятии с публикации `ingest_document` удаляет чанки.
- Ошибки HTTP/API эмбеддингов при **поиске** перехватываются: возвращается пустой список, исключение логируется. При **индексации** ошибка пробрасывается после лога (старые чанки не удаляются до успешного ответа API).
- Добавлены юнит-тесты `tests/test_rag_chunking.py`, `tests/test_rag_service.py`; интеграционный тест репозитория дополнен проверкой исключения черновиков из поиска.

## Какие файлы изменены

- `src/medvopros/db/constants.py` — константа `DOCUMENT_STATUS_PUBLISHED`.
- `src/medvopros/repositories/chunk_repo.py` — join с `documents`, фильтр `published`, подгрузка `document.slug` в сессии.
- `src/medvopros/rag/__init__.py`, `chunking.py`, `embeddings.py`, `ingest.py`, `search.py` — новые.
- `src/medvopros/services/rag_service.py` — новый.
- `src/medvopros/services/__init__.py` — экспорт `RagService`, `ChunkHit`, `default_embedder`.
- `tests/test_repositories_db.py`, `tests/test_rag_chunking.py`, `tests/test_rag_service.py`.
- `README.md` — раздел про RAG.

## Что проверить вручную

- Задать валидный **`LLM_API_KEY`** (или `OPENAI_API_KEY`) и при необходимости **`LLM_BASE_URL`**; убедиться, что **`[rag] embedding_model`** и **`embedding_dimensions`** соответствуют ответу API (для `text-embedding-3-small` — 1536).
- После индексации опубликованного документа проверить строки в `document_chunks` и поиск запросом, близким к тексту.

## Риски

- Стоимость и **rate limits** API эмбеддингов при полной переиндексации большого корпуса; в коде есть батчи и backoff при 429/5xx.
- Несовпадение размерности вектора с типом `vector(N)` в PostgreSQL при смене модели без миграции и переиндексации.

## Проверка успешности этапа (Agent 05 — RAG)

| Шаг | Действие | Ожидание | Результат |
|-----|----------|----------|-----------|
| 1 | Опубликованный тестовый документ в БД (через админку или фикстуру) | Документ со статусом `published` | OK/FAIL |
| 2 | Запуск индексации (UI или вызов сервиса) | В `document_chunks` появились строки, размерность вектора = конфигу | OK/FAIL |
| 3 | Поиск по запросу, близкому к содержимому документа | Top-k не пустой, score выше порога | OK/FAIL |
| 4 | Запрос вне темы базы | Промах или score ниже порога (как по [04_rag_design.md](../04_rag_design.md)) | OK/FAIL |
| 5 | Снятие документа с публикации + повтор поиска | Чанки не участвуют или удалены | OK/FAIL |
| 6 | Ошибка API эмбеддингов (симуляция или обрыв сети) | Процесс не падает; задокументированное поведение | OK/FAIL |
| 7 | Логи/metadata содержат chunk ids или scores для отладки | Соответствие контракту `AnswerService`/RAG | OK/FAIL |
| 8 | Сверка с [12_acceptance_checklist.md](../12_acceptance_checklist.md), блок **B** (B2–B5) | Отмечено | OK/FAIL |

**Параметры для приёмки (из `config.ini`):** `min_similarity` = **0.72**, модель эмбеддингов = **`text-embedding-3-small`** (ключ API в `.env`, не публиковать).

Этап **успешен**, если шаги **2, 3, 6** — OK (критерий из задания агента).
