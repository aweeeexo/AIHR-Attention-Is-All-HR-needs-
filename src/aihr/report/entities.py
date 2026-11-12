"""Проверка сущностей в сгенерированном тексте (T09, шаг 8; принцип 6).

Сущности: числа и годы, слова латиницей, слова с заглавной буквы не в начале предложения, термины
словаря синонимов. Каждая должна найтись в фактах, переданных в генерацию. Не нашлась — текст
считается непроверенным: повтор генерации, затем откат к шаблону.
"""

from __future__ import annotations

import re

from aihr.normalize.synonyms import find_terms

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_LATIN = re.compile(r"(?<![\w])[A-Za-z][A-Za-z0-9+#.\-]*[A-Za-z0-9+#]|(?<![\w])[A-Za-z](?![\w])")
_CAPITAL = re.compile(r"(?<![.!?»\n]\s)(?<!^)(?<=\s)[А-ЯЁ][а-яё]{2,}")
_STEM = 5  # слово совпало, если совпали первые 5 букв — «Python» и «Python-разработка», падежи

# Оценки личности и признаки, по которым нельзя судить о кандидате (T09, шаг 4)
STOP_PHRASES = re.compile(
    r"(?i)ленив|неопытн|безответствен|недалёк|недалек|глуп|странн\w+ человек|возраст|молод\w+ для"
    r"|стар\w+ для|пенсион|женщин|мужчин|пол\b|беремен|декрет|семейн\w+ положен|дет(?:и|ей)\b"
    r"|национальн|религ|внешност|здоровь"
)


def entities(text: str) -> list[str]:
    found: list[str] = []
    found += _NUMBER.findall(text)
    found += [m.group(0) for m in _LATIN.finditer(text)]
    found += [m.group(0) for m in _CAPITAL.finditer(text)]
    found += [f"={t}" for t in find_terms(text)]
    out: list[str] = []
    for e in found:
        if e not in out:
            out.append(e)
    return out


def _known(entity: str, facts: str, fact_terms: set[str]) -> bool:
    if entity.startswith("="):
        return entity[1:] in fact_terms
    low = entity.lower().replace("ё", "е")
    if _NUMBER.fullmatch(entity):
        return re.search(rf"(?<!\d){re.escape(low)}(?!\d)", facts) is not None
    key = low[:_STEM] if len(low) > _STEM else low
    return key in facts


def unverified(text: str, facts: str) -> list[str]:
    """Сущности текста, которых нет в фактах."""
    facts_low = facts.lower().replace("ё", "е")
    fact_terms = set(find_terms(facts))
    return [e for e in entities(text) if not _known(e, facts_low, fact_terms)]


def has_stop_phrase(text: str) -> bool:
    return STOP_PHRASES.search(text) is not None
