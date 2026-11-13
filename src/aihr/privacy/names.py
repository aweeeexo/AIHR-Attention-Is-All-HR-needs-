"""ФИО: кандидат (имя файла, первые строки, NER в контактах), другие люди (NER), склонения."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_CYR_WORD = re.compile(r"^[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?$")
_FILENAME_NOISE = re.compile(r"(?i)резюме|resume|\bcv\b|\d+")
_NAME_GRAMMEMES = {"Name", "Surn", "Patr"}


@lru_cache
def _morph() -> Any:
    from natasha import MorphVocab

    return MorphVocab()


@lru_cache
def _ner() -> tuple[Any, Any]:
    from natasha import NewsEmbedding, NewsNERTagger, Segmenter

    return Segmenter(), NewsNERTagger(NewsEmbedding())


def is_name_word(word: str) -> bool:
    """Слово с заглавной буквы, которое словарь знает как имя, фамилию или отчество."""
    if not _CYR_WORD.match(word) or len(word) < 2:
        return False
    for part in word.split("-"):
        if any(_NAME_GRAMMEMES & set(p.tag.grammemes) for p in _morph().parse(part)):
            return True
    return False


def names_from_filename(filename: str) -> list[str]:
    stem = _FILENAME_NOISE.sub(" ", Path(filename).stem)
    words = [w for w in re.split(r"[\s_.,()-]+", stem) if w]
    return [w for w in words if is_name_word(w)]


def names_from_line(line: str) -> list[str]:
    """Первая строка резюме вида «Иванов Алексей Петрович» — 2–3 слова-имени, без цифр."""
    words = line.replace(",", " ").split()
    if not 2 <= len(words) <= 4 or any(ch.isdigit() for ch in line) or len(line) > 60:
        return []
    names = [w for w in words if is_name_word(w)]
    return names if len(names) >= 2 else []


def person_spans(text: str) -> list[tuple[int, int, str]]:
    """Спаны PER из Natasha, только из слов с заглавной кириллической буквы."""
    if not re.search(r"[А-ЯЁ][а-яё]+", text):
        return []
    from natasha import Doc

    segmenter, tagger = _ner()
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_ner(tagger)
    out = []
    for span in doc.spans:
        if span.type != "PER":
            continue
        words = span.text.split()
        if words and all(
            _CYR_WORD.match(w.strip(".,")) or re.match(r"^[А-ЯЁ]\.$", w) for w in words
        ):
            out.append((span.start, span.stop, span.text))
    return out


def location_spans(text: str) -> list[tuple[int, int, str]]:
    from natasha import Doc

    segmenter, tagger = _ner()
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_ner(tagger)
    return [(s.start, s.stop, s.text) for s in doc.spans if s.type == "LOC"]


def _stem(word: str) -> str:
    """Основа для склонений: «Петрова» → «Петров», «Алексей» → «Алексе», «Иванов» → «Иванов»."""
    if len(word) >= 4 and word[-1] in "аяйьео":  # «Анна» → «Анн»: Анны, Анне, Анной
        return word[:-1]
    if len(word) >= 6 and word[-2:] in ("ий", "ый", "ая", "ой"):
        return word[:-2]
    return word


def name_pattern(word: str) -> re.Pattern[str]:
    """Все падежи слова-имени: основа + до 3 букв окончания. Регистр важен: «Роман», не «роман»."""
    stem = _stem(word)
    title = re.escape(stem).replace("е", "[её]").replace("Е", "[ЕЁ]")
    upper = re.escape(stem.upper()).replace("Е", "[ЕЁ]")
    return re.compile(rf"(?<![\w-])(?:{title}[а-яё]{{0,3}}|{upper}[А-ЯЁ]{{0,3}})(?![\w])")
