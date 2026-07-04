"""Resolve configured paths relative to repository root."""

from __future__ import annotations

from pathlib import Path

from vetvopros.config.settings import Settings


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_under_repo(relative: str) -> Path:
    return (repo_root() / relative).resolve()


def read_texts_file(settings: Settings, filename: str) -> str:
    return (resolve_under_repo(settings.paths.texts_dir) / filename).read_text(encoding="utf-8")


def read_prompt_file(settings: Settings, relative_path: str) -> str:
    return resolve_under_repo(relative_path).read_text(encoding="utf-8")
