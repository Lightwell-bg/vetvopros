# VetVopros на VPS (Docker)

Инструкция для сервера, на котором **Docker и Docker Compose уже установлены** (плагин `docker compose` или классический `docker-compose` — ниже по умолчанию используется **`docker compose`**).

## Архитектура (как договорились)

| Компонент | Где живёт |
|-----------|-----------|
| **PostgreSQL** + расширение **pgvector** | Отдельный контейнер `vetvopros-db` |
| **Данные БД** | **Только** именованный Docker volume **`vetvopros_pgdata`** (не каталог на хосте) |
| **Telegram-бот** и **веб-админка** | **Один** контейнер `vetvopros-app` (сначала поднимается uvicorn/FastAPI, параллельно long polling бота) |
| **Админка в браузере** | Адрес вида **`http://<IP_вашего_VPS>:<порт>/`** — **без** SSH-туннеля, **без** reverse proxy и **без** SSL (только для доверенной сети / теста; пароль и сессии всё равно защищайте, см. раздел про безопасность) |

Файлы в репозитории:

| Файл | Назначение |
|------|------------|
| `Dockerfile` | Сборка образа приложения (Python, зависимости, `config.ini`, `texts/`, `prompts/`, Alembic) |
| `docker-compose.yml` | Сервисы **`db`** и **`app`**, volume только `pgdata` |
| `docker/entrypoint-app.sh` | Старт: `alembic upgrade head` → фон **`run_admin.py`** → фон **`run_bot.py`**, ожидание бота; корректное завершение по SIGTERM |
| `deploy/env.docker.example` | Шаблон `.env` для сервера |

---

## Шаг 1. Подключиться к VPS по SSH

На Windows можно использовать **PowerShell**, **Windows Terminal**, **PuTTY**, **MobaXterm** или встроенный SSH в редакторе.

Пример (замените пользователя и IP):

```bash
ssh ubuntu@203.0.113.50
```

После входа вы окажетесь в домашнем каталоге пользователя (часто `/home/ubuntu`).

Проверьте Docker (команды **без** `sudo`, если пользователь уже в группе `docker`):

```bash
docker --version
docker compose version
```

Если видите версии — идём дальше. Если «permission denied» — выполните одну команду с `sudo` или добавьте пользователя в группу `docker` (один раз):

```bash
sudo usermod -aG docker "$USER"
```

и перелогиньтесь в SSH.

---

## Шаг 2. Получить код проекта на сервер

### Вариант A — через Git (удобно для обновлений)

```bash
cd ~
git clone <URL_вашего_репозитория> vetvopros
cd vetvopros
```

Дальше **все команды** выполняйте из каталога **`vetvopros`**, где лежат `docker-compose.yml` и `Dockerfile`.

### Вариант B — загрузка архива

1. На своём ПК скачайте архив репозитория (ZIP с GitHub/GitLab).
2. Загрузите на VPS инструментом **SCP**, **WinSCP**, **FileZilla** и т.п. в домашний каталог.
3. На сервере:

```bash
cd ~
unzip vetvopros-main.zip
cd vetvopros-main
```

(имя папки может отличаться — зайдите в ту, где есть `docker-compose.yml`.)

---

## Шаг 3. Настроить `config.ini` под продакшен

Откройте файл в редакторе на сервере:

```bash
nano config.ini
```

(В `nano`: правите текст, сохранение **Ctrl+O**, Enter, выход **Ctrl+X**.)

Обязательно в секции **`[app]`**:

```ini
environment = production
```

Так в консоль контейнера почти ничего не пишется (см. основной `README.md`). Для отладки временно можно поставить `development` или `staging`.

Проверьте остальные секции: **`[telegram]`**, **`[billing]`**, **`[rag]`**, **`[specialist_*]`**. Секреты (**токен бота**, ключи API) **не** кладите в `config.ini` — только в `.env`.

Если позже захотите менять `config.ini` **без пересборки образа**, можно добавить в `docker-compose.yml` у сервиса `app` том (после первого успешного деплоя):

```yaml
    volumes:
      - ./config.ini:/app/config.ini:ro
```

Тогда правите `./config.ini` на диске сервера и выполняете:

```bash
docker compose restart app
```

---

## Шаг 4. Создать файл `.env` с секретами

1. Скопируйте шаблон:

```bash
cp deploy/env.docker.example .env
```

2. Откройте `.env`:

```bash
nano .env
```

3. Заполните минимум:

| Переменная | Зачем |
|------------|--------|
| `POSTGRES_PASSWORD` | Пароль пользователя БД. Лучше **не** использовать в пароле символы `@ : / ? # &` — иначе разбор URL `DATABASE_URL` может сломаться. |
| `TELEGRAM_BOT_TOKEN` | Токен от [@BotFather](https://t.me/BotFather). |
| `LLM_API_KEY` | Ключ LLM (или вашего совместимого провайдера). |
| `ADMIN_SESSION_SECRET` | Длинная случайная строка для подписи cookie сессии админки. |
| `ADMIN_PASSWORD` | Пароль входа в веб-админку. |

4. **Не указывайте** в этом `.env` строку `DATABASE_URL=...` для Docker: `docker-compose.yml` сам подставит подключение к контейнеру **`db`** по имени сервиса. Если оставить старый `DATABASE_URL` с `localhost`, переменная из compose обычно **перекроет** её для контейнера `app`, но проще не дублировать и убрать `DATABASE_URL` из серверного `.env`.

5. Ограничьте права на файл:

```bash
chmod 600 .env
```

Опционально: порт админки **на хосте** (снаружи), если 8000 занят:

```bash
# в .env
ADMIN_HOST_PORT=8080
```

Внутри контейнера админка по-прежнему слушает **8000**; в `docker-compose.yml` сопоставление: `ADMIN_HOST_PORT` на хосте → `8000` в контейнере. Менять **`VETVOPROS_ADMIN_PORT`** в `.env` для Docker не нужно, если не меняете правую часть `ports` в compose вручную.

Опционально: увеличить максимально допустимый размер текста документа (Markdown) при сохранении через админку.
Это **несекретная** настройка, задаётся в `config.ini`:

```ini
[admin]
max_form_bytes = 10485760
```

---

## Шаг 5. Открыть порт админки в фаерволе VPS

Админка будет доступна как **`http://<публичный_IP_VPS>:8000/`** (или другой `ADMIN_HOST_PORT`).

Если на сервере включён **UFW** (Ubuntu):

```bash
sudo ufw status
```

Если UFW активен, разрешите SSH (если ещё не разрешён) и порт админки, **затем** включите/обновите правила:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8000/tcp
sudo ufw reload
sudo ufw status
```

Если используете другой порт из `ADMIN_HOST_PORT`, подставьте его вместо `8000`.

**У облачного провайдера** (AWS Security Group, Hetzner Firewall, Timeweb и т.д.) может быть **отдельная** сетка правил: добавьте входящий TCP на тот же порт для вашего IP или для теста — осторожно — «откуда угодно».

---

## Шаг 6. Первый запуск

Из **корня репозитория** (где `docker-compose.yml`):

```bash
docker compose up -d --build
```

Что происходит:

1. Скачивается образ **`pgvector/pgvector:pg16-bookworm`** (если его ещё нет локально).
2. Собирается образ **`vetvopros:local`**.
3. Запускается контейнер **`vetvopros-db`**, создаётся volume **`vetvopros_pgdata`**, данные PostgreSQL хранятся **только** там.
4. После `healthy` у БД запускается **`vetvopros-app`**:
   - выполняется **`alembic upgrade head`**;
   - в фоне — **`python src/run_admin.py`** (слушает **`0.0.0.0:8000`** внутри контейнера);
   - в фоне — **`python src/run_bot.py`**;
   - скрипт ждёт завершения процесса бота; при остановке контейнера оба процесса получают сигнал завершения.

Флаг **`init: true`** у сервиса `app` в compose включает лёгкий init-процесс (корректный репarent/zombie reaping для фоновых процессов).

Проверка:

```bash
docker compose ps
```

Оба сервиса должны быть в состоянии **`running`** (у `db` ещё может отображаться **`healthy`**).

Откройте в браузере (с любого ПК, с учётом фаервола):

```text
http://64.23.190.210:8081/
```

(или ваш `ADMIN_HOST_PORT`.) Должна открыться форма входа админки. Бота проверьте в Telegram.

Логи (в `production` вывода может почти не быть):

```bash
docker compose logs -f app
docker compose logs -f db
```

Остановка контейнеров **без** удаления данных БД:

```bash
docker compose down
```

Данные в volume **`vetvopros_pgdata`** сохраняются.

**Полное удаление** контейнеров и **тома с БД** (все данные PostgreSQL пропадут):

```bash
docker compose down -v
```

---

## Шаг 7. Безопасность при схеме «HTTP без SSL»

Сейчас трафик между браузером и админкой **не шифруется**: пароль и cookie сессии теоретически могут быть перехвачены в той же сети. Рекомендации:

- Используйте **сложный** `ADMIN_PASSWORD` и уникальный **`ADMIN_SESSION_SECRET`**.
- По возможности открывайте порт админки **только для своего IP** (фаервол провайдера + UFW).
- Для публичного интернета позже подключите **HTTPS** (например, Caddy/Nginx + Let’s Encrypt) и закройте прямой доступ к порту 8000 снаружи.

Telegram-бот к вашему серверу **входящих подключений от пользователей не требует** — он сам ходит в API Telegram.

---

## Полезные команды

| Задача | Команда |
|--------|---------|
| Статус | `docker compose ps` |
| Логи приложения | `docker compose logs -f --tail=200 app` |
| Перезапуск только приложения | `docker compose restart app` |
| Пересборка образа без кэша | `docker compose build --no-cache app` |
| Разовый запуск Alembic без старта бота | `docker compose run --rm app alembic current` |
| Обновить только миграции вручную | `docker compose run --rm app alembic upgrade head` |
| Shell внутри контейнера приложения | `docker compose run --rm --entrypoint sh app` |
| Где физически лежит volume (диагностика) | `docker volume inspect vetvopros_pgdata` |

---

## Обновление бота и админки после изменений в репозитории

Работайте на сервере в **корне проекта** (где `docker-compose.yml`).

### 1. Обновить код (Git)

```bash
cd ~/vetvopros
git pull
```

(или ваш путь к клону.)

### 2. Пересобрать образ и перезапустить

```bash
docker compose up -d --build
```

При старте контейнера **`app`** снова выполнится **`alembic upgrade head`** — новые миграции применятся сами.

### 3. Проверить

```bash
docker compose ps
docker compose logs --tail=80 app
```

### Если меняли только `config.ini` на сервере

- Без тома в compose: пересоберите образ (`docker compose up -d --build`), так как `config.ini` **вшит** в образ при сборке.
- С томом `./config.ini:/app/config.ini:ro`: достаточно

```bash
docker compose restart app
```

### Если добавили зависимости в `pyproject.toml`

Обязательно полная пересборка:

```bash
docker compose build --no-cache app
docker compose up -d
```
На будущее (обновление)
На VPS из /opt/vetvopros:

git pull
docker compose up -d --build
Если менял только .env:
docker compose up -d --force-recreate

### Бэкап базы перед крупным обновлением

```bash
docker exec vetvopros-db pg_dump -U vetvopros vetvopros > backup_$(date +%F).sql
```

(логин/БД замените, если меняли `POSTGRES_USER` / `POSTGRES_DB`.)

---

## Частые проблемы

| Симптом | Что проверить |
|---------|----------------|
| `app` постоянно перезапускается | `docker compose logs app` — нет токена, ошибка LLM, ошибка миграций, неверный `DATABASE_URL` |
| Не открывается админка по IP | UFW, фаервол облака, порт в `ports`, контейнер `app` running |
| Бот молчит | Токен, лимиты Telegram, логи `app` (временно `environment=development` в `config.ini` и пересборка) |
| Ошибки pgvector | Образ БД должен быть **`pgvector/pgvector`**, миграции применены |

---

Дополнительно: общий обзор проекта — **[README.md](README.md)**, конфигурация — **[09_config_and_env.md](09_config_and_env.md)**.
