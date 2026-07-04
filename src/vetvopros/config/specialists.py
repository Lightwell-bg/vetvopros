"""Load [specialist_*] sections from config.ini."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpecialistCard:
    key: str
    display_name: str
    telegram_user_id: int | None
    telegram_username: str | None
    url: str | None
    note: str | None


def load_specialists(ini_path: Path) -> list[SpecialistCard]:
    parser = configparser.ConfigParser()
    read = parser.read(ini_path, encoding="utf-8")
    if not read:
        return []
    out: list[SpecialistCard] = []
    for section in parser.sections():
        if not section.startswith("specialist_"):
            continue
        key = section.removeprefix("specialist_")
        items = dict(parser.items(section))
        tu = (items.get("telegram_username") or "").strip()
        tid_raw = (items.get("telegram_user_id") or "").strip()
        telegram_user_id: int | None = None
        if tid_raw.isdigit():
            telegram_user_id = int(tid_raw)
        url = (items.get("url") or "").strip()
        note = (items.get("note") or "").strip() or None
        out.append(
            SpecialistCard(
                key=key,
                display_name=(items.get("display_name") or key).strip(),
                telegram_user_id=telegram_user_id,
                telegram_username=tu or None,
                url=url or None,
                note=note,
            )
        )
    return out
