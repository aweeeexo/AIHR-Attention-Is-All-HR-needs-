"""Разбор дат из резюме кодом (D13). Модель только переписывает raw_dates как есть.

Точка периода: «03.2021», «3/2021», «2021-03», «март 2021», «Mar 2021», «2021» (только год —
приближённо, середина года: июль), «по н.в.» и синонимы — текущий месяц.
Период: «2019 — 2021», «с 2019 по 2021», «с 03.2019» (без конца — по настоящее время).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aihr.contracts import YearMonth

APPROX_MONTH = 7  # год без месяца: берём середину года, чтобы не завышать и не занижать стаж

_MONTHS: dict[str, int] = {}
for _num, _forms in enumerate(
    [
        "январь января янв jan january",
        "февраль февраля фев февр feb february",
        "март марта мар mar march",
        "апрель апреля апр apr april",
        "май мая may",
        "июнь июня июн jun june",
        "июль июля июл jul july",
        "август августа авг aug august",
        "сентябрь сентября сен сент sep sept september",
        "октябрь октября окт oct october",
        "ноябрь ноября ноя нояб nov november",
        "декабрь декабря дек dec december",
    ],
    1,
):
    for _form in _forms.split():
        _MONTHS[_form] = _num

_MONTH_NAME = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR = r"(?:19[5-9]\d|20[0-4]\d)"
_POINT = re.compile(
    rf"(?P<mm>\b(?:0?[1-9]|1[0-2]))\s*[./]\s*(?P<y1>{_YEAR})\b"
    rf"|\b(?P<name>{_MONTH_NAME})\.?\s+(?P<y2>{_YEAR})\b"
    rf"|\b(?P<y3>{_YEAR})\b",
    re.IGNORECASE,
)
_ISO = re.compile(rf"\b({_YEAR})-(0[1-9]|1[0-2])\b")
_CURRENT = re.compile(
    r"по\s*н\.?\s*в\.?|н\.\s*в\.?|по\s+наст|настоящ\w*\s+(?:время|момент)|сейчас|до\s+сих\s+пор"
    r"|\b(?:present|current|now|till\s+now|to\s+date|ongoing)\b",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"\s*(?:—|–|‐|-|−|\bпо\b|\bдо\b|\bto\b|\btill\b)\s*", re.IGNORECASE)
_DURATION = re.compile(
    r"(?:(?P<y>\d{1,2})\s*(?:год|года|лет|г\.|years?|yrs?))?\s*"
    r"(?:(?P<m>\d{1,2})\s*(?:месяц\w*|мес\.?|months?|mos?))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Point:
    ym: YearMonth
    approximate: bool


@dataclass(frozen=True)
class Period:
    start: YearMonth
    end: YearMonth
    is_current: bool
    approximate: bool


def month_index(ym: YearMonth) -> int:
    """Номер месяца для арифметики. Без месяца — середина года."""
    return ym.year * 12 + (ym.month or APPROX_MONTH) - 1


def parse_point(text: str) -> Point | None:
    m = _POINT.search(_ISO.sub(lambda x: f"{x.group(2)}.{x.group(1)}", text))
    if not m:
        return None
    if m.group("y1"):
        return Point(YearMonth(year=int(m.group("y1")), month=int(m.group("mm"))), False)
    if m.group("y2"):
        month = _MONTHS[m.group("name").lower()]
        return Point(YearMonth(year=int(m.group("y2")), month=month), False)
    return Point(YearMonth(year=int(m.group("y3"))), True)


def parse_period(raw: str | None, today: YearMonth) -> Period | None:
    """None, если в строке нет ни одной даты начала."""
    if not raw or not raw.strip():
        return None
    text = _ISO.sub(lambda x: f"{x.group(2)}.{x.group(1)}", raw.strip())
    since = re.match(r"^\s*(?:с|from|since)\s+", text, flags=re.IGNORECASE)
    if since:
        text = text[since.end() :]
    current_match = _CURRENT.search(text)
    head = text[: current_match.start()] if current_match else text
    parts = [p for p in _SPLIT.split(head, maxsplit=1) if p.strip()]
    if not parts:
        return None
    start = parse_point(parts[0])
    if start is None:
        return None
    end: Point | None = parse_point(parts[1]) if len(parts) > 1 else None
    is_current = current_match is not None or (end is None and since is not None)
    if is_current:
        end = Point(today, False)
    elif end is None:
        # Одна дата без «с» и без «по н.в.»: работа в пределах этого года или месяца
        if start.approximate:
            y = start.ym.year
            return Period(YearMonth(year=y, month=1), YearMonth(year=y + 1, month=1), False, True)
        return Period(start.ym, start.ym, False, False)
    assert end is not None
    if month_index(end.ym) < month_index(start.ym):
        return None  # «2023 — 2019»: опечатка, лучше не считать, чем считать неверно
    return Period(start.ym, end.ym, is_current, start.approximate or end.approximate)


def parse_duration(text: str) -> int | None:
    """«5 лет 3 месяца» → 63. Готовая длительность hh.ru — только для сверки, не вместо дат."""
    for m in _DURATION.finditer(text):
        years, months = m.group("y"), m.group("m")
        if years or months:
            return int(years or 0) * 12 + int(months or 0)
    return None
