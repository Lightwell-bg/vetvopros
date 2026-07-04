# VetVopros: один контейнер — Telegram-бот + веб-админка (см. docker/entrypoint-app.sh).
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY config.ini ./
COPY texts ./texts
COPY prompts ./prompts

RUN pip install --upgrade pip && pip install .

COPY docker/entrypoint-app.sh /entrypoint-app.sh
RUN sed -i 's/\r$//' /entrypoint-app.sh && chmod +x /entrypoint-app.sh

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/entrypoint-app.sh"]
CMD ["run"]
