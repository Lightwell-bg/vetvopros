"""Утилиты загрузки пользовательских markdown-текстов из каталога `texts/`."""

from vetvopros.texts.markdown_loader import load_texts_markdown, parse_keyword_lines

__all__ = ["load_texts_markdown", "parse_keyword_lines"]
