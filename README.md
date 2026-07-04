# VetVopros

Ветеринарный справочный Telegram-бот на Python с RAG (векторный поиск по базе знаний) и LLM, а также веб-админкой на FastAPI.

> **Что умеет бот:** даёт справочные ответы на вопросы о здоровье домашних питомцев — кошек, собак, кроликов, грызунов, птиц, рептилий. Не ставит диагноз, не заменяет ветеринарного врача. При реально критичных симптомах (судороги, остановка дыхания, отравление и т.д.) направляет в ветклинику. При лёгких симптомах — рекомендует наблюдение дома или плановый визит к ветеринару (без лишней тревоги).

---

## Технологии

| Слой | Технология |
|------|-----------|
| Бот | aiogram 3.x |
| Веб-админка | FastAPI + Jinja2 |
| База данных | PostgreSQL + pgvector |
| Эмбеддинги и LLM | OpenAI API (или совместимый) |
| RAG | pgvector + cosine similarity |
| Миграции | Alembic |
| Деплой | Docker Compose |

---

## Структура проекта

```
vetvopros/
├── src/
│   ├── vetvopros/         # Основной Python-пакет
│   │   ├── admin/         # FastAPI-админка (маршруты, шаблоны)
│   │   ├── billing/       # Логика биллинга (бесплатные лимиты, подписки, пакеты)
│   │   ├── bot/           # Telegram-бот (app_factory, keyboards, middleware)
│   │   ├── config/        # Настройки (settings.py, paths.py)
│   │   ├── db/            # Модели, сессия, схема
│   │   ├── handlers/      # Хэндлеры aiogram (меню, анализы, специалист-релей)
│   │   ├── rag/           # Загрузка документов (ingest) и поиск
│   │   ├── repositories/  # Слой доступа к БД
│   │   ├── services/      # Бизнес-логика (VetAnswerService, LlmService)
│   │   ├── texts/         # Загрузчик текстов .md
│   │   └── vet/           # Ветеринарные guardrails (red flags)
│   ├── run_bot.py         # Точка входа для бота
│   └── run_admin.py       # Точка входа для веб-админки
├── texts/                 # Пользовательские тексты (дисклеймеры, red flags и т.д.)
├── prompts/               # LLM-промпты (system_prompt.md, analysis_*.md)
├── alembic/               # Миграции БД
├── tests/                 # Юнит-тесты
├── config.ini             # Несекретные настройки
├── .env.example           # Шаблон .env
├── docker-compose.yml     # Docker Compose (БД + приложение)
└── Dockerfile
```

---

## Быстрый старт (локально)

### 1. Клонирование и виртуальное окружение

```bash
git clone <repo-url>
cd vetvopros
python -m venv .venv
source .venv/Scripts/activate   # Windows (Git Bash / VS Code Terminal)
# или: .venv\Scripts\activate.bat  # Windows CMD
# или: .venv/bin/activate          # Linux / macOS
pip install -e .
```

### 2. Конфигурация

Скопируйте `.env.example` в `.env` и заполните значения:

```bash
cp .env.example .env
```

Минимально необходимые переменные в `.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/vetvopros
TELEGRAM_BOT_TOKEN=your-bot-token
LLM_API_KEY=your-openai-api-key
ADMIN_SESSION_SECRET=random-long-string
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-admin-password
```

Остальные настройки — в `config.ini` (несекретные: имя приложения, пути к текстам, параметры RAG, специалисты и т.д.).

> Путь к `config.ini` при необходимости переопределяйте через `VETVOPROS_CONFIG_INI=/path/to/config.ini`.

### 3. PostgreSQL с pgvector

Установите [pgvector](READMEPGVECTOR.md) или используйте Docker-образ:

```bash
docker run -d --name vetvopros-db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=vetvopros \
  -p 5432:5432 \
  pgvector/pgvector:pg16-bookworm
```

### 4. Миграции

```bash
alembic upgrade head
```

Или включите автоприменение миграций в `config.ini`:

```ini
[bot]
; При environment = development миграции применяются автоматически при старте бота.
environment = development
```

### 5. Запуск

```bash
# Бот (в одном терминале)
source .venv/Scripts/activate
python src/run_bot.py

# Веб-админка (в другом терминале)
source .venv/Scripts/activate
python src/run_admin.py
```

Админка по умолчанию: http://127.0.0.1:8080

---

## Docker Compose (продакшен / тест)

```bash
cp deploy/env.docker.example .env
# Отредактируйте .env
docker compose up -d --build
```

Сервисы:
- `vetvopros-db` — PostgreSQL с pgvector
- `vetvopros-app` — бот + админка

Данные БД хранятся в volume `vetvopros_pgdata`.

---

## Настройка внешних сервисов (API)

### Telegram Bot

1. Создайте бота у [@BotFather](https://t.me/BotFather).
2. Скопируйте токен в `TELEGRAM_BOT_TOKEN` в `.env`.
3. В `config.ini` укажите Telegram group/admin IDs при необходимости:
   ```ini
   [telegram]
   group_id = 0
   admin_user_ids = 123456789
   ```

### LLM / Embeddings (OpenAI API или совместимый)

```dotenv
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1   # опционально; если пусто — стандартный OpenAI
```

В `config.ini` настройте модели:

```ini
[llm]
model = gpt-4o-mini
embedding_model = text-embedding-3-small
max_tokens = 1024
temperature = 0.3
```

---

## База данных и миграции

- Имя БД по умолчанию: `vetvopros`
- Схема управляется Alembic (папка `alembic/`)
- Расширение `vector` должно быть установлено (включено в образ `pgvector/pgvector`)

Применить все миграции:

```bash
alembic upgrade head
```

Откатить последнюю:

```bash
alembic downgrade -1
```

Автосоздание БД (если ещё нет) при старте бота:

```dotenv
VETVOPROS_AUTO_CREATE_DB=true
```

Автоприменение миграций при старте:

```dotenv
VETVOPROS_AUTO_MIGRATE=true
```

---

## RAG (загрузка документов в базу знаний)

Инструмент загрузки документов (`rag/ingest.py`). Документы добавляются через **веб-админку** (`/documents`) или напрямую через скрипты.

Параметры RAG в `config.ini`:

```ini
[rag]
top_k = 5
min_similarity = 0.7
chunk_size = 800
chunk_overlap = 100
```

---

## Биллинг и лимиты

Бот поддерживает:
- **Бесплатные лимиты** (количество ответов ассистента и сообщений специалисту в месяц)
- **Подписки** (безлимитные или с квотой по периоду)
- **Пакеты** (разовые покупки дополнительных ответов)
- **Идемпотентность** — повторные запросы не списывают кредиты дважды

Параметры лимитов в `config.ini`:

```ini
[billing]
free_answers_limit = 5
free_specialist_messages_limit = 3
```

---

## Ветеринарные guardrails (red flags)

Файл `src/vetvopros/vet/guardrails.py` содержит список **критичных ветеринарных ситуаций**. При их обнаружении в тексте пользователя бот отвечает шаблоном из `texts/red_flag_response.md` (направляет в ветклинику) и **не вызывает LLM**.

Правила намеренно **краткие**: только реально опасные состояния (остановка дыхания, судороги, отравления, острая задержка мочи у кота, заворот желудка, тепловой удар и т.д.). **Лёгкие симптомы** (кашель, одноразовая рвота, плохой аппетит) guardrails не перехватывают — LLM отвечает в обычном режиме.

Дополнительные ключевые фразы можно добавить в `texts/red_flags_keywords.md`.

---

## Ветеринарные специалисты

Список специалистов настраивается в `config.ini`:

```ini
[specialist_general_vet]
display_name = Ветеринар общей практики
telegram_user_id = 123456789   ; числовой Telegram ID специалиста

[specialist_surgeon_vet]
display_name = Ветеринар-хирург
telegram_user_id = 0           ; 0 = не настроен
```

Пользователь выбирает специалиста в меню, бот пересылает сообщение. Ответы специалиста приходят обратно пользователю через релей.

---

## Тесты

```bash
source .venv/Scripts/activate
pytest tests/ -m "not integration" -q
```

Интеграционные тесты (требуют реальную БД):

```bash
pytest tests/ -q
```

---

## Веб-админка

Доступна по адресу `http://<host>:<VETVOPROS_ADMIN_PORT>/`

Маршруты:
- `/` — документы
- `/documents` — управление документами базы знаний
- `/status` — статус приложения
- `/audit` — журнал событий
- `/health` — health check (JSON)

Логин/пароль задаются в `.env`:

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-password
```

---

## Переменные окружения (справочник)

| Переменная | Описание |
|-----------|----------|
| `DATABASE_URL` | SQLAlchemy URL PostgreSQL (обязательна) |
| `TELEGRAM_BOT_TOKEN` | Токен бота (обязателен) |
| `LLM_API_KEY` | Ключ OpenAI API (обязателен) |
| `LLM_BASE_URL` | Базовый URL API (опционально) |
| `ADMIN_SESSION_SECRET` | Секрет подписи cookie (обязателен) |
| `ADMIN_USERNAME` | Логин в админку (обязателен) |
| `ADMIN_PASSWORD` | Пароль в админку (обязателен) |
| `VETVOPROS_CONFIG_INI` | Путь к config.ini (опционально) |
| `VETVOPROS_ADMIN_HOST` | Хост сервера админки (по умолчанию 0.0.0.0) |
| `VETVOPROS_ADMIN_PORT` | Порт сервера админки (по умолчанию 8000) |
| `VETVOPROS_ADMIN_RELOAD` | Авторезагрузка uvicorn (false в проде) |
| `VETVOPROS_AUTO_MIGRATE` | Автоприменение миграций при старте |
| `VETVOPROS_AUTO_CREATE_DB` | Автосоздание БД при старте |

---

## Примечание про историю проекта

Папка `agents/` содержит отчёты и ТЗ, созданные в рамках исходного проекта **MedVopros** (медицинские консультации для людей). Они оставлены как история и **не относятся к текущей ветеринарной версии**. Функциональная кодовая база полностью переработана под ветеринарный домен.
