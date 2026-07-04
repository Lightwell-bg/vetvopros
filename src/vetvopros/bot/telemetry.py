"""Lightweight Telegram forwarding (group notifications)."""

from __future__ import annotations

import html
import re
from contextlib import suppress

from aiogram import Bot

from vetvopros.config.settings import Settings


def _user_line(*, user_id: int, full_name: str | None, username: str | None) -> str:
    un = (username or "").strip()
    un_fmt = f"@{un}" if un else "—"
    name = (full_name or "").strip() or "—"
    return f"id={user_id} name={name} username={un_fmt}"


def _escape(s: str) -> str:
    return html.escape(s or "", quote=False)


_RE_FENCED = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_RE_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _md_to_plain(md: str) -> str:
    """Best-effort Markdown → plain text for telemetry forwarding."""
    s = (md or "").replace("\r\n", "\n").strip()
    if not s:
        return ""
    # Remove fenced blocks (often large).
    s = _RE_FENCED.sub("", s)
    # Links: keep text + url.
    s = _RE_LINK.sub(r"\1 (\2)", s)
    # Inline code: keep content.
    s = _RE_INLINE_CODE.sub(r"\1", s)
    # Headings / blockquotes / horizontal rules.
    s = re.sub(r"^\s{0,3}#{1,6}\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s{0,3}>\s?", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s{0,3}(-{3,}|_{3,}|\*{3,})\s*$", "", s, flags=re.MULTILINE)
    # Basic emphasis markers.
    s = s.replace("**", "").replace("*", "").replace("__", "").replace("_", "")
    # Stray backticks (if any).
    s = s.replace("`", "")
    # Collapse excessive blank lines.
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


async def forward_start_event(
    bot: Bot,
    settings: Settings,
    *,
    user_id: int,
    full_name: str | None,
    username: str | None,
) -> None:
    """Notify configured groups about /start."""
    group_ids = list(getattr(settings, "telegram_group_ids", []) or [])
    if not group_ids:
        return
    text = "🟢 /start\n" + _escape(_user_line(user_id=user_id, full_name=full_name, username=username))
    for gid in group_ids:
        with suppress(Exception):
            await bot.send_message(gid, text)


async def forward_qa_event(
    bot: Bot,
    settings: Settings,
    *,
    user_id: int,
    full_name: str | None,
    username: str | None,
    question: str,
    answer: str,
    source: str,
) -> None:
    """Notify configured groups about a question + assistant answer."""
    group_ids = list(getattr(settings, "telegram_group_ids", []) or [])
    if not group_ids:
        return
    header = "❓ Q&A\n" + _escape(_user_line(user_id=user_id, full_name=full_name, username=username))
    q = _md_to_plain(question)
    a = _md_to_plain(answer)
    body = (
        f"{header}\n\n"
        f"source={_escape(source)}\n\n"
        f"ВОПРОС:\n{_escape(q)}\n\n"
        f"ОТВЕТ:\n{_escape(a)}"
    )
    # Telegram limit: 4096. Hard cut to keep robust.
    if len(body) > 3800:
        body = body[:3797] + "..."
    for gid in group_ids:
        with suppress(Exception):
            await bot.send_message(gid, body)

