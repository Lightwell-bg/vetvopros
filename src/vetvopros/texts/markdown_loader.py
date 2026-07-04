"""Загрузка фрагментов из `texts/*.md` по именам файлов из настроек (`config.ini` → `[paths]`).

Этот слой не дублирует `read_texts_file`: переиспользуется низкоуровневое чтение с диска.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from vetvopros.config.paths import read_texts_file, resolve_under_repo
from vetvopros.config.settings import Settings


def load_texts_markdown(settings: Settings, filename: str) -> str:
    """Прочитать markdown-файл из каталога `paths.texts_dir` (путь относительно корня репозитория)."""
    return read_texts_file(settings, filename)


def parse_keyword_lines(raw: str) -> tuple[str, ...]:
    """Разобрать строки ключевых слов: пустые и строки, начинающиеся с `#`, пропускаются."""
    out: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return tuple(out)


@lru_cache(maxsize=32)
def _cached_extra_keywords(path_str: str, mtime_ns: int) -> tuple[str, ...]:
    p = Path(path_str)
    return parse_keyword_lines(p.read_text(encoding="utf-8"))


def load_extra_red_flag_keywords(settings: Settings) -> tuple[str, ...]:
    """Подстроки из `red_flags_keywords_file`; кэш по пути и mtime (изменение файла подхватывается)."""
    root = resolve_under_repo(settings.paths.texts_dir)
    path = root / settings.paths.red_flags_keywords_file
    if not path.is_file():
        return ()
    st = path.stat()
    return _cached_extra_keywords(str(path.resolve()), int(st.st_mtime_ns))
