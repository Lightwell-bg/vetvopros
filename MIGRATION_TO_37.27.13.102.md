# Перенос VetVopros на новый сервер 37.27.13.102

Инструкция для переноса проекта **со всеми данными** со старого VPS на новый (`37.27.13.102`), где Docker уже настроен и пользователь имеет `sudo`. Код передаётся через **GitHub**, данные (дамп БД, `.env`, `config.ini`) — через **WinSCP** (старый сервер → ваш ПК → новый сервер).

Архитектура проекта: 2 контейнера (`db` — Postgres+pgvector, `app` — бот+админка), все данные — **только** в именованном Docker-volume `vetvopros_pgdata`. Файлового хранилища вне БД нет, поэтому перенос данных = перенос дампа PostgreSQL.

---

## Шаг 0. Что понадобится

- SSH-доступ к старому серверу и к новому (`37.27.13.102`).
- Токен GitHub (у вас уже есть) — для `git push`/`git clone` приватного репозитория.
- WinSCP на Windows, подключённый к обоим серверам (можно поочерёдно).
- На новом сервере: Docker + Docker Compose (уже есть), пользователь в sudo.

---

## Шаг 1. Залить актуальный код в GitHub (со старого сервера или локально)

Если код на старом сервере отличается от того, что в GitHub (правки на проде), сначала синхронизируйте:

```bash
# на старом сервере, в каталоге проекта (обычно /opt/vetvopros)
cd /opt/vetvopros
git status
git add -A
git commit -m "sync before migration to new server"
git push origin main
```

Если правок не было — просто убедитесь, что `main` в GitHub актуален.

---

## Шаг 2. Сделать дамп базы данных на старом сервере

```bash
cd /opt/vetvopros
docker exec vetvopros-db pg_dump -U vetvopros -d vetvopros -F c -f /tmp/vetvopros_backup.dump
docker cp vetvopros-db:/tmp/vetvopros_backup.dump ~/vetvopros_backup.dump
ls -la ~/vetvopros_backup.dump
```

(логин/БД замените, если на старом сервере другие `POSTGRES_USER`/`POSTGRES_DB` — смотрите `.env` на старом сервере.)

Формат `-F c` (custom) — компактный и восстанавливается через `pg_restore`, годится для переноса на pgvector-образ той же версии.

**Важно:** копируйте именно в домашний каталог (`~`), а не в `/opt/vetvopros` — если `/opt/vetvopros` принадлежит `root` (типично для каталогов, разворачиваемых через `sudo`/CI), обычный пользователь не сможет туда записать файл: `docker cp` завершится без ошибки на стадии стриминга, но сам файл не создастся. Проверьте `ls -la ~/vetvopros_backup.dump` — размер должен быть не нулевым.

Файл `~/vetvopros_backup.dump` (например, `/home/vlad/vetvopros_backup.dump`) появится в домашнем каталоге на старом сервере — его и заберёте через WinSCP.

---

## Шаг 3. Скачать через WinSCP со старого сервера на свой ПК

В WinSCP подключитесь к старому серверу и скачайте к себе на диск:

- `~/vetvopros_backup.dump` (домашний каталог, например `/home/vlad/vetvopros_backup.dump`)
- `/opt/vetvopros/.env` (реальные секреты — токен бота, ключ LLM, пароли)
- `/opt/vetvopros/config.ini` (если правился вручную на проде и отличается от того, что в git)

Если WinSCP не даёт зайти в `/opt/vetvopros` для чтения `.env`/`config.ini` из-за прав — прочитайте их через SSH и скопируйте содержимое себе, либо на старом сервере временно `sudo cp .env config.ini ~/ && sudo chown vlad:vlad ~/.env ~/config.ini`, заберите через WinSCP, затем удалите копии из `~`.

Больше ничего переносить не нужно — весь код придёт через `git clone`.

---

## Шаг 4. Подготовить проект на новом сервере (37.27.13.102)

```bash
ssh <ваш_пользователь>@37.27.13.102
sudo mkdir -p /opt
sudo chown "$USER":"$USER" /opt
cd /opt
git clone https://<ВАШ_GITHUB_ТОКЕН>@github.com/Lightwell-bg/vetvopros.git vetvopros
cd /opt/vetvopros
```

(Не оставляйте токен в истории команд надолго — после клонирования можно переключить remote на SSH-ключ или на HTTPS без токена в URL:
`git remote set-url origin https://github.com/Lightwell-bg/vetvopros.git`, а креды для будущих `git pull` настроить через `git credential store`/SSH-ключ.)

---

## Шаг 5. Залить через WinSCP на новый сервер

В WinSCP подключитесь к `37.27.13.102` и загрузите в `/opt/vetvopros/`:

- `vetvopros_backup.dump`
- `.env`
- `config.ini` (если отличался от версии в git)

```bash
chmod 600 /opt/vetvopros/.env
```

---

## Шаг 6. Поднять контейнеры на новом сервере (сначала без прогона старых миграций поверх пустой БД — восстановим дамп)

```bash
cd /opt/vetvopros
docker compose up -d db
```

Подождите, пока БД станет `healthy`:

```bash
docker compose ps
```

---

## Шаг 7. Восстановить дамп в новый контейнер БД

```bash
docker cp ./vetvopros_backup.dump vetvopros-db:/tmp/vetvopros_backup.dump
docker exec vetvopros-db pg_restore -U vetvopros -d vetvopros --clean --if-exists /tmp/vetvopros_backup.dump
```

Если при создании volume `db` уже сама накатила пустую схему (Alembic ещё не запускался, т.к. `app` не стартовал) — флаг `--clean --if-exists` безопасно снесёт пустые таблицы перед восстановлением. Ошибки вида `role "vetvopros" already exists` при `-F c` дампе можно игнорировать — это нормально.

Проверка, что данные на месте:

```bash
docker exec -it vetvopros-db psql -U vetvopros -d vetvopros -c "\dt"
docker exec -it vetvopros-db psql -U vetvopros -d vetvopros -c "SELECT count(*) FROM users;"
```

---

## Шаг 8. Запустить приложение (бот + админка)

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=80 app
```

При старте контейнера `app` выполнится `alembic upgrade head` — на восстановленной из дампа БД он просто подтвердит, что все миграции уже применены (если версии совпадают с тем, что было на старом сервере).

---

## Шаг 9. Открыть порт админки в фаерволе нового сервера

**Сначала проверьте фактический порт на хосте** — он берётся из `ADMIN_HOST_PORT` в `.env` и может отличаться от 8000 (если в `.env` этого сервера стоит другое значение):

```bash
docker compose ps
```

В колонке `PORTS` будет что-то вроде `0.0.0.0:8081->8000/tcp` — значит снаружи сайт слушает **8081**, а не 8000. Дальше везде подставляйте именно этот порт.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 8081/tcp
sudo ufw reload
sudo ufw status
```

(замените `8081` на ваш реальный порт из `docker compose ps`.)

Плюс правило в панели хостинга (Cloud Firewall провайдера — у Hetzner/DigitalOcean и т.п. это отдельный уровень фильтрации поверх UFW), если используется: разрешите входящий TCP на тот же порт.

Быстрая проверка **локально на сервере** (не зависит от фаервола) — если это `200`/редирект, контейнер работает и проблема именно в фаерволе/порте:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/
```

Откройте в браузере: `http://37.27.13.102:8081/` (порт — из `docker compose ps`) — должна открыться форма входа админки с теми же логином/паролем, что был на старом сервере (они пришли вместе с `.env`).

Если хотите вернуть стандартный порт 8000: поправьте `ADMIN_HOST_PORT=8000` в `.env` и выполните `docker compose up -d --force-recreate app`.

---

## Шаг 10. Проверить бота

В Telegram отправьте боту тестовое сообщение — должен ответить. Логи:

```bash
docker compose logs -f app
```

---

## Шаг 11. Остановить старый сервер

Только после того как убедились, что новый сервер полностью рабочий (бот отвечает, админка открывается, данные на месте):

```bash
ssh <пользователь>@<старый_сервер>
cd /opt/vetvopros
docker compose down
```

Это остановит контейнеры **без** удаления volume `vetvopros_pgdata` на старом сервере — на случай, если данные понадобится свериться ещё раз. Позже, когда убедитесь, что всё перенесено, можно удалить volume (`docker compose down -v`) или вовсе снести проект.

Не забудьте также:
- Отключить/удалить cron-задачи или systemd-юниты, если бот запускался не только через Docker Compose.
- В Telegram у бота **не** может быть двух активных long-polling инстансов одновременно — до остановки старого сервера новый может конфликтовать (получать `409 Conflict` от Telegram API). Поэтому короткое окно между шагом 8 (новый сервер стартует) и шагом 11 (старый останавливается) — норма, но не затягивайте: оставьте старый бот включённым до проверки нового, затем сразу гасите старый.

---

## Проверка после переноса

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://37.27.13.102:8000/
docker compose ps
```

Ожидается `200` (или редирект на страницу логина) и оба сервиса `running`/`healthy`.
