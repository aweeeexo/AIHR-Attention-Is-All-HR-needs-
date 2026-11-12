"""Нормализация текста фрагментов: Unicode, пробелы, маркеры списков, нарезка длинных абзацев."""

from __future__ import annotations

import re
import unicodedata

MAX_FRAGMENT_CHARS = 400

_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"))
_SPACES = re.compile(r"[\s   ]+")
# Маркер в начале строки: символ-буллет или номер «1.» / «1)». Год «2019 –» не номер
_BULLET = re.compile(r"^\s*(?:[•·▪▫◦●○■□➢➤►▶✓✔\-–—*]|\d{1,2}[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?…;])\s+(?=[«\"(\[A-ZА-ЯЁ0-9])")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_INVISIBLE)
    return _SPACES.sub(" ", text).strip()


def strip_bullet(text: str) -> tuple[str, bool]:
    """Убирает маркер списка из начала строки. Возвращает (текст, был ли маркер)."""
    m = _BULLET.match(text)
    if not m or not text[m.end() :].strip():
        return text, False
    return text[m.end() :].strip(), True


def split_long(text: str, limit: int = MAX_FRAGMENT_CHARS) -> list[str]:
    """Режет длинный абзац по предложениям в куски не длиннее limit (если предложение длиннее — целиком)."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def join_wrapped_lines(lines: list[str]) -> list[str]:
    """Склейка строк pdf: перенос слова «разра-/ботка» и строка, продолжающая предложение."""
    out: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            out.append("")
            continue
        if out and out[-1]:
            prev = out[-1]
            starts_lower = line[0].islower()
            if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha() and starts_lower:
                out[-1] = prev[:-1] + line
                continue
            if starts_lower and not _BULLET.match(line) and prev[-1] not in ".:;!?":
                out[-1] = f"{prev} {line}"
                continue
        out.append(line)
    return out
