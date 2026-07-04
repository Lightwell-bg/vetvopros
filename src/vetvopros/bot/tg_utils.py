"""Telegram message limits."""

from __future__ import annotations

import asyncio
import html
import re
from contextlib import suppress
from typing import Awaitable, TypeVar

from aiogram import Bot
from aiogram.enums import ChatAction

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_T = TypeVar("_T")


def chunk_text(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Legacy splitter (hard cut). Prefer `chunk_paragraphs` for formatted text."""
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        parts.append(rest[:limit])
        rest = rest[limit:]
    return parts


def chunk_paragraphs(text: str, limit: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split by paragraphs first to avoid breaking markup."""
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]
    paras = re.split(r"\n{2,}", text.strip())
    out: list[str] = []
    cur = ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        candidate = (cur + ("\n\n" if cur else "") + p) if cur else p
        if len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            out.append(cur)
            cur = ""
        if len(p) <= limit:
            cur = p
            continue
        # fallback: very long paragraph
        out.extend(chunk_text(p, limit=limit))
    if cur:
        out.append(cur)
    return out


_RE_FENCED = re.compile(r"```(.*?)```", re.DOTALL)
_RE_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_BOLD = re.compile(r"\*\*([^\n*][\s\S]*?)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*([^\n*][\s\S]*?)\*(?!\*)")


def md_to_tg_html(md: str) -> str:
    """Very small Markdown → Telegram HTML converter for `texts/*.md`.

    Supports: headings, bullet lists, **bold**, *italic*, `code`, ```code blocks```, [text](url).
    Output is safe HTML (escaped), suitable for `parse_mode="HTML"`.
    """
    src = (md or "").replace("\r\n", "\n")
    if not src.strip():
        return ""

    # Escape first; we'll insert tags after.
    escaped = html.escape(src, quote=False)

    # Fenced code blocks first.
    def _fenced(m: re.Match[str]) -> str:
        inner = m.group(1).strip("\n")
        return f"<pre><code>{inner}</code></pre>"

    escaped = _RE_FENCED.sub(_fenced, escaped)

    # Links.
    escaped = _RE_LINK.sub(r'<a href="\2">\1</a>', escaped)

    # Inline code.
    escaped = _RE_INLINE_CODE.sub(r"<code>\1</code>", escaped)

    # Headings -> bold line.
    lines: list[str] = []
    for line in escaped.split("\n"):
        m = re.match(r"^\s*(#{1,6})\s+(.*)\s*$", line)
        if m:
            lines.append(f"<b>{m.group(2).strip()}</b>")
        else:
            lines.append(line)
    escaped = "\n".join(lines)

    # Bullet lists: "- " at line start.
    escaped = re.sub(r"^\s*-\s+", "• ", escaped, flags=re.MULTILINE)

    # Bold / italic.
    escaped = _RE_BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _RE_ITALIC.sub(r"<i>\1</i>", escaped)

    return escaped


async def run_with_chat_action(
    bot: Bot,
    chat_id: int,
    coro: Awaitable[_T],
    *,
    action: ChatAction = ChatAction.TYPING,
    interval_seconds: float = 4.0,
) -> _T:
    """Run coroutine while periodically sending chat action (typing, upload, etc.)."""
    stop = False

    async def _ticker() -> None:
        while not stop:
            try:
                await bot.send_chat_action(chat_id, action)
            except Exception:
                # Chat actions are best-effort; don't fail the main flow.
                pass
            await asyncio.sleep(max(1.0, float(interval_seconds)))

    task = asyncio.create_task(_ticker())
    try:
        return await coro
    finally:
        stop = True
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
