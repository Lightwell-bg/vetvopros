"""Load `config.ini` (non-secrets) and `.env` / environment (secrets)."""

from __future__ import annotations

import configparser
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from vetvopros.config.constants import DEFAULT_CONFIG_INI


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _env_file_paths() -> tuple[str, ...]:
    paths: list[str] = []
    root_env = _repo_root() / ".env"
    if root_env.is_file():
        paths.append(str(root_env))
    paths.append(".env")
    return tuple(paths)


def resolve_config_ini_path(explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            msg = f"config.ini not found at {p}"
            raise FileNotFoundError(msg)
        return p.resolve()
    cwd_candidate = Path.cwd() / DEFAULT_CONFIG_INI
    if cwd_candidate.is_file():
        return cwd_candidate.resolve()
    root_candidate = _repo_root() / DEFAULT_CONFIG_INI
    if root_candidate.is_file():
        return root_candidate.resolve()
    msg = (
        "config.ini not found. Place it in the project root or current working directory, "
        "or set VETVOPROS_CONFIG_INI."
    )
    raise FileNotFoundError(msg)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_csv_ints(raw: str) -> list[int]:
    parts = [p.strip() for p in (raw or "").split(",")]
    out: list[int] = []
    for p in parts:
        if not p:
            continue
        out.append(int(p))
    return out


class _EnvSecrets(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file_paths(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    llm_base_url: str | None = Field(default=None, validation_alias="LLM_BASE_URL")
    admin_session_secret: str = Field(
        default="", validation_alias="ADMIN_SESSION_SECRET"
    )
    admin_username: str = Field(default="admin", validation_alias="ADMIN_USERNAME")
    admin_password: str = Field(default="", validation_alias="ADMIN_PASSWORD")
    admin_uvicorn_host: str = Field(
        default="0.0.0.0", validation_alias="VETVOPROS_ADMIN_HOST"
    )
    admin_uvicorn_port: int = Field(
        default=8000, validation_alias="VETVOPROS_ADMIN_PORT"
    )
    admin_uvicorn_reload: bool = Field(
        default=False, validation_alias="VETVOPROS_ADMIN_RELOAD"
    )
    payment_provider: str = Field(default="stub", validation_alias="PAYMENT_PROVIDER")
    payment_webhook_secret: str = Field(
        default="", validation_alias="PAYMENT_WEBHOOK_SECRET"
    )
    config_ini_path: str | None = Field(
        default=None, validation_alias="VETVOPROS_CONFIG_INI"
    )


class IniPaths(BaseModel):
    texts_dir: str
    prompts_dir: str
    system_prompt_file: str
    prompt_analysis_suggestions: str
    prompt_analysis_interpretation: str
    prompt_analysis_multiturn_suggestions: str = Field(
        default="prompts/analysis_multiturn_suggestions.md",
    )
    prompt_analysis_multiturn_interpretation: str = Field(
        default="prompts/analysis_multiturn_interpretation.md",
    )
    red_flag_response_file: str = Field(default="red_flag_response.md")
    red_flags_keywords_file: str = Field(default="red_flags_keywords.md")
    analysis_interpretation_disclaimer_file: str = Field(
        default="analysis_interpretation_disclaimer.md"
    )


class IniRag(BaseModel):
    chunk_size_chars: int
    chunk_overlap_chars: int
    top_k: int
    min_similarity: float
    max_context_chunks: int
    embedding_model: str
    embedding_dimensions: int


class IniLlm(BaseModel):
    chat_model: str
    request_timeout_seconds: int
    max_output_tokens: int
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    reduce_log_detail: bool = False
    history_messages: int = 8


class IniFeatures(BaseModel):
    enable_analyses_flow: bool
    enable_specialist_menu: bool
    auto_index_on_publish: bool


class IniAdmin(BaseModel):
    # Максимальный размер form-body для админки (для больших Markdown документов).
    max_form_bytes: int = 10 * 1024 * 1024


class IniBilling(BaseModel):
    free_answers_per_user: int
    free_specialist_messages_per_user: int
    specialist_message_cost: int
    chargeable_answer_sources: str = (
        "rag_llm,rag,llm,analysis_suggestions,analysis_interpretation"
    )


class Settings(BaseModel):
    """Combined application settings (ini + env). Secrets come only from environment / `.env`."""

    app_name: str
    environment: str
    log_level: str

    paths: IniPaths
    database_pool_size: int
    telegram_polling_timeout: int
    telegram_group_ids: list[int] = Field(default_factory=list)
    telegram_admin_ids: list[int] = Field(default_factory=list)
    rag: IniRag
    llm: IniLlm
    features: IniFeatures
    admin: IniAdmin = Field(default_factory=IniAdmin)
    billing: IniBilling

    database_url: str
    telegram_bot_token: str
    llm_api_key: str
    llm_base_url: str | None
    admin_session_secret: str
    admin_username: str
    admin_password: str
    admin_uvicorn_host: str
    admin_uvicorn_port: int
    admin_uvicorn_reload: bool
    payment_provider: str
    payment_webhook_secret: str

    config_ini_path: Path

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, v: str) -> str:
        return v.upper()

    def validate_for_bot(self) -> None:
        missing: list[str] = []
        if not self.telegram_bot_token.strip():
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.llm_api_key.strip():
            missing.append("LLM_API_KEY or OPENAI_API_KEY")
        if not self.database_url.strip():
            missing.append("DATABASE_URL")
        if missing:
            msg = "Missing required environment variables for bot: " + ", ".join(
                missing
            )
            raise ValueError(msg)

    def validate_for_admin(self) -> None:
        missing: list[str] = []
        if not self.database_url.strip():
            missing.append("DATABASE_URL")
        if (
            not self.admin_session_secret.strip()
            or self.admin_session_secret == "change-me-to-random-long-string"
        ):
            missing.append("ADMIN_SESSION_SECRET (set a strong random value)")
        if not (self.admin_password or "").strip():
            missing.append("ADMIN_PASSWORD")
        if missing:
            msg = "Missing or weak admin configuration: " + ", ".join(missing)
            raise ValueError(msg)


def _section_dict(parser: configparser.ConfigParser, name: str) -> dict[str, str]:
    if not parser.has_section(name):
        msg = f"Missing [{name}] in config.ini"
        raise ValueError(msg)
    return {k: v for k, v in parser.items(name)}


def _optional_section_dict(parser: configparser.ConfigParser, name: str) -> dict[str, str]:
    if not parser.has_section(name):
        return {}
    return {k: v for k, v in parser.items(name)}


def _load_ini(path: Path) -> dict[str, Any]:
    parser = configparser.ConfigParser()
    read = parser.read(path, encoding="utf-8")
    if not read:
        msg = f"Could not read config file: {path}"
        raise OSError(msg)

    app = _section_dict(parser, "app")
    paths = _section_dict(parser, "paths")
    db = _section_dict(parser, "database")
    telegram = _section_dict(parser, "telegram")
    rag = _section_dict(parser, "rag")
    llm = _section_dict(parser, "llm")
    features = _section_dict(parser, "features")
    admin = _optional_section_dict(parser, "admin")
    billing = _section_dict(parser, "billing")

    return {
        "app_name": app["name"],
        "environment": app["environment"],
        "log_level": app["log_level"],
        "paths": paths,
        "database_pool_size": int(db["pool_size"]),
        "telegram_polling_timeout": int(telegram["polling_timeout"]),
        "telegram_group_ids": _parse_csv_ints(telegram.get("group_ids", "")),
        "telegram_admin_ids": _parse_csv_ints(telegram.get("admin_ids", "")),
        "rag": {
            "chunk_size_chars": int(rag["chunk_size_chars"]),
            "chunk_overlap_chars": int(rag["chunk_overlap_chars"]),
            "top_k": int(rag["top_k"]),
            "min_similarity": float(rag["min_similarity"]),
            "max_context_chunks": int(rag["max_context_chunks"]),
            "embedding_model": rag["embedding_model"],
            "embedding_dimensions": int(rag["embedding_dimensions"]),
        },
        "llm": {
            "chat_model": llm["chat_model"],
            "request_timeout_seconds": int(llm["request_timeout_seconds"]),
            "max_output_tokens": int(llm["max_output_tokens"]),
            "max_retries": int(llm.get("max_retries", "2")),
            "retry_backoff_seconds": float(llm.get("retry_backoff_seconds", "1.0")),
            "reduce_log_detail": _parse_bool(llm.get("reduce_log_detail", "false")),
            "history_messages": int(llm.get("history_messages", "8")),
        },
        "features": {
            "enable_analyses_flow": _parse_bool(features["enable_analyses_flow"]),
            "enable_specialist_menu": _parse_bool(features["enable_specialist_menu"]),
            "auto_index_on_publish": _parse_bool(features["auto_index_on_publish"]),
        },
        "admin": {
            "max_form_bytes": int(admin.get("max_form_bytes", str(10 * 1024 * 1024))),
        },
        "billing": {
            "free_answers_per_user": int(billing["free_answers_per_user"]),
            "free_specialist_messages_per_user": int(
                billing["free_specialist_messages_per_user"]
            ),
            "specialist_message_cost": int(billing["specialist_message_cost"]),
            "chargeable_answer_sources": billing.get(
                "chargeable_answer_sources",
                "rag_llm,rag,llm,analysis_suggestions,analysis_interpretation",
            ),
        },
    }


def load_settings(*, config_ini: str | None = None) -> Settings:
    env = _EnvSecrets()
    ini_path = resolve_config_ini_path(config_ini or env.config_ini_path)
    ini_data = _load_ini(ini_path)
    return Settings(
        **ini_data,
        database_url=env.database_url,
        telegram_bot_token=env.telegram_bot_token,
        llm_api_key=env.llm_api_key,
        llm_base_url=env.llm_base_url,
        admin_session_secret=env.admin_session_secret,
        admin_username=env.admin_username,
        admin_password=env.admin_password,
        admin_uvicorn_host=env.admin_uvicorn_host,
        admin_uvicorn_port=env.admin_uvicorn_port,
        admin_uvicorn_reload=env.admin_uvicorn_reload,
        payment_provider=env.payment_provider,
        payment_webhook_secret=env.payment_webhook_secret,
        config_ini_path=ini_path,
    )


@lru_cache
def get_settings() -> Settings:
    explicit = os.environ.get("VETVOPROS_CONFIG_INI")
    return load_settings(config_ini=explicit)


def clear_settings_cache() -> None:
    """Clear cached settings (e.g. in tests)."""
    get_settings.cache_clear()
