"""Structured JSON logging to stdout; в ``environment=production`` — без вывода в консоль."""

from __future__ import annotations

import json
import logging
import sys
import warnings
from datetime import UTC, datetime
from typing import Any

# Выше любого стандартного уровня (CRITICAL=50), чтобы не пропускать записи на root.
_SILENCE_ROOT_LEVEL = 100


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "structured", None)
        if isinstance(extra, dict):
            payload["extra"] = extra
        return json.dumps(payload, ensure_ascii=False)


def is_production_environment(environment: str | None) -> bool:
    return (environment or "").strip().lower() == "production"


def uvicorn_silent_log_config() -> dict[str, Any]:
    """Конфиг для ``uvicorn.run(log_config=...)``: без stdout/stderr от uvicorn/access."""
    null = "logging.NullHandler"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"_void": {"class": null}},
        "root": {"handlers": ["_void"], "level": "CRITICAL"},
        "loggers": {
            "uvicorn": {"handlers": ["_void"], "level": "CRITICAL", "propagate": False},
            "uvicorn.error": {"handlers": ["_void"], "level": "CRITICAL", "propagate": False},
            "uvicorn.access": {"handlers": ["_void"], "level": "CRITICAL", "propagate": False},
        },
    }


def setup_logging(
    level: str = "INFO",
    *,
    use_json: bool = True,
    environment: str | None = None,
) -> None:
    """Настроить корневой логгер.

    При ``environment=production`` — убрать вывод в консоль (NullHandler + завышенный уровень root).
    """
    root = logging.getLogger()
    if is_production_environment(environment):
        warnings.filterwarnings("ignore")
        for h in list(root.handlers):
            root.removeHandler(h)
        root.addHandler(logging.NullHandler())
        root.setLevel(_SILENCE_ROOT_LEVEL)
        return

    if root.handlers:
        root.setLevel(level)
        return

    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
