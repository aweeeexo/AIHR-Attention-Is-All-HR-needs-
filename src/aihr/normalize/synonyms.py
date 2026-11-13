"""Синонимы (D14, T06-A): словарь data/synonyms.yaml — точные синонимы, сокращения, написания.

Смежные навыки — не синонимы: у них общий class (skill_class), а не общий канон.
Омонимы («ПМ» — проектный менеджер или программа-минимум) canonicalize() не склеивает:
возвращает None, смысл решает LLM. Сравнение без регистра, ё = е, «1С» = «1C».
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

_LAT_CYR = str.maketrans({"с": "c"})  # «1с» (кириллица) = «1c»
_EDGE_PUNCT = " \t.,;:!?()[]«»\"'"


def norm(term: str) -> str:
    t = term.lower().replace("ё", "е").strip(_EDGE_PUNCT)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*([-/.])\s*", r"\1", t)  # «react . js» → «react.js», «a / b» → «a/b»
    if re.fullmatch(r"\d+с", t):  # «1с» — кириллическая «с» после цифры
        t = t.translate(_LAT_CYR)
    return t


@dataclass(frozen=True)
class Dictionary:
    by_alias: dict[str, str]
    aliases: dict[str, list[str]]
    classes: dict[str, str | None]
    homonyms: frozenset[str]
    pattern: re.Pattern[str] | None


def _compile(aliases: list[str]) -> re.Pattern[str] | None:
    if not aliases:
        return None
    parts = sorted({re.escape(a) for a in aliases}, key=len, reverse=True)
    return re.compile(r"(?<![\w+#])(?:" + "|".join(parts) + r")(?![\w+#])")


def _path() -> Path:
    from aihr.config import get_settings

    return get_settings().synonyms_path


@lru_cache(maxsize=4)
def _load(path: Path) -> Dictionary:
    if not path.is_file():
        log.warning("словарь синонимов не найден: %s — слой синонимов выключен", path)
        return Dictionary({}, {}, {}, frozenset(), None)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    homonyms = frozenset(norm(str(h)) for h in raw.get("homonyms", []))
    by_alias: dict[str, str] = {}
    aliases: dict[str, list[str]] = {}
    classes: dict[str, str | None] = {}
    for canon, spec in (raw.get("terms") or {}).items():
        names = [str(a) for a in spec.get("aliases", [])]
        aliases[canon] = names
        classes[canon] = spec.get("class")
        for alias in [canon.replace("_", " "), *names]:
            key = norm(alias)
            if key and key not in homonyms:
                by_alias.setdefault(key, canon)
    return Dictionary(by_alias, aliases, classes, homonyms, _compile(list(by_alias)))


def dictionary() -> Dictionary:
    return _load(_path().resolve())


_VERSION = re.compile(r"\s*v?\d+(?:\.\d+)*\+?$")


def canonicalize(term: str) -> str | None:
    """«Автокад» → «autocad», «Python 3.11» → «python»; неизвестное и омонимы → None."""
    d = dictionary()
    key = norm(term)
    if not key or key in d.homonyms:
        return None
    if key in d.by_alias:
        return d.by_alias[key]
    stripped = _VERSION.sub("", key)  # «python 3.11» → «python»
    if stripped != key and stripped in d.by_alias:
        return d.by_alias[stripped]
    return None


def aliases(canonical: str) -> list[str]:
    return list(dictionary().aliases.get(canonical, []))


def skill_class(canonical: str) -> str | None:
    """Класс навыка для смежных доказательств: AutoCAD и Компас — оба cad."""
    return dictionary().classes.get(canonical)


def _normalized_for_search(text: str) -> str:
    t = text.lower().replace("ё", "е")
    return re.sub(r"(?<=\d)с\b", "c", t)  # «1С» → «1c»


def find_terms(text: str) -> list[str]:
    """Канонические термины, встретившиеся в тексте, в порядке появления, без повторов."""
    d = dictionary()
    if d.pattern is None or not text:
        return []
    found: list[str] = []
    for m in d.pattern.finditer(_normalized_for_search(text)):
        canon = d.by_alias.get(norm(m.group(0)))
        if canon and canon not in found:
            found.append(canon)
    return found


def normalize_text(text: str) -> str:
    """Текст с алиасами, заменёнными каноническими токенами — для BM25 и сравнения."""
    d = dictionary()
    if d.pattern is None:
        return text
    return d.pattern.sub(
        lambda m: d.by_alias.get(norm(m.group(0)), m.group(0)), _normalized_for_search(text)
    )
