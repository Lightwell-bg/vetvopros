#!/bin/sh
# Один контейнер: миграции → админка (фон) → бот (фон), ждём бота; SIGTERM/SIGINT — останавливаем оба.
cd /app || exit 1

if [ "$1" = "alembic" ]; then
  shift
  exec alembic "$@"
fi

if [ "$1" != "run" ]; then
  exec "$@"
fi

set -e
alembic upgrade head

python src/run_admin.py &
admin_pid=$!

# Если админка упала сразу (часто из-за отсутствующих env), лучше зафейлить контейнер,
# иначе получается «бот работает, веб нет» без явной ошибки.
sleep 1
if ! kill -0 "$admin_pid" 2>/dev/null; then
  wait "$admin_pid" 2>/dev/null || true
  exit 1
fi

python src/run_bot.py &
bot_pid=$!

trap 'kill -TERM "$admin_pid" "$bot_pid" 2>/dev/null; wait 2>/dev/null; exit 143' TERM INT

wait "$bot_pid"
status=$?
kill -TERM "$admin_pid" 2>/dev/null
wait "$admin_pid" 2>/dev/null || true
exit "$status"
