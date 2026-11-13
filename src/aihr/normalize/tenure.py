"""Стаж кодом (D13): длительность мест работы, объединение периодов, стаж по навыку, перерывы.

Длительность — разница месяцев: 03.2021–06.2024 = 39 мес. = 3 г. 3 мес. (как в контракте).
Работа, начатая и законченная в одном месяце, — 1 месяц. Пересекающиеся периоды не
складываются дважды.
"""

from __future__ import annotations

import itertools

from aihr.contracts import CandidateProfile, Position, YearMonth
from aihr.normalize.dates import month_index, parse_period
from aihr.normalize.levels import cefr_from_text

GAP_MONTHS = 6  # перерыв длиннее — в gaps_months (риск для T09, без оценок)

Interval = tuple[int, int]  # [начало, конец) в номерах месяцев


def months_between(start: YearMonth, end: YearMonth) -> int:
    return max(1, month_index(end) - month_index(start))


def _interval(pos: Position) -> Interval | None:
    if pos.start is None or pos.end is None:
        return None
    a = month_index(pos.start)
    return a, a + months_between(pos.start, pos.end)


def union(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def tenure_for(positions: list[Position]) -> tuple[int | None, bool]:
    """Стаж по набору мест работы: (месяцы или None, если дат нет; приближённо ли)."""
    intervals = [iv for p in positions if (iv := _interval(p)) is not None]
    if not intervals:
        return None, False
    total = sum(b - a for a, b in union(intervals))
    approximate = any(p.dates_approximate for p in positions if _interval(p) is not None)
    return total, approximate


def format_months(months: int | None, approximate: bool = False) -> str:
    """39 → «3 г. 3 мес.», с «≈», если даты известны только по годам."""
    if months is None:
        return "не указано"
    years, rest = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} г.")
    if rest or not years:
        parts.append(f"{rest} мес.")
    return ("≈ " if approximate else "") + " ".join(parts)


def _ym(index: int) -> YearMonth:
    return YearMonth(year=index // 12, month=index % 12 + 1)


def _with_dates(pos: Position, today: YearMonth) -> Position:
    update: dict[str, object] = {}
    if pos.start is None and pos.raw_dates:
        period = parse_period(pos.raw_dates, today)
        if period is not None:
            update = {
                "start": period.start,
                "end": period.end,
                "is_current": period.is_current,
                "dates_approximate": period.approximate,
            }
    elif pos.start is not None and pos.end is None and pos.is_current:
        update = {"end": today}
    pos = pos.model_copy(update=update) if update else pos
    if pos.start is not None and pos.end is not None:
        pos = pos.model_copy(update={"duration_months": months_between(pos.start, pos.end)})
    return pos


def enrich_profile(profile: CandidateProfile, today: YearMonth) -> CandidateProfile:
    positions = [_with_dates(p, today) for p in profile.positions]
    total, _ = tenure_for(positions)

    merged = union([iv for p in positions if (iv := _interval(p)) is not None])
    gaps = [
        (_ym(prev_end), _ym(next_start))
        for (_, prev_end), (next_start, _) in itertools.pairwise(merged)
        if next_start - prev_end > GAP_MONTHS
    ]

    skills = []
    for skill in profile.skills:
        names = {skill.name.lower(), (skill.canonical or "").lower()} - {""}
        used = [
            p
            for p in positions
            if set(skill.fragment_ids) & set(p.fragment_ids) or names & {t.lower() for t in p.tools}
        ]
        months, _ = tenure_for(used)
        last = max((p.end.year for p in used if p.end is not None), default=None)
        skills.append(
            skill.model_copy(
                update={
                    "years": round(months / 12, 1) if months is not None else None,
                    "last_used_year": last,
                }
            )
        )

    languages = [
        lang.model_copy(update={"cefr": lang.cefr or cefr_from_text(lang.level_raw or "")})
        for lang in profile.languages
    ]
    return profile.model_copy(
        update={
            "positions": positions,
            "skills": skills,
            "languages": languages,
            "total_experience_months": total,
            "gaps_months": gaps,
        }
    )
