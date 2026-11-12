"""Стаж кодом (D13). T00: длительность мест работы с известными датами и их сумма.

T05: разбор raw_dates, объединение пересекающихся периодов, стаж по навыку, перерывы.
"""

from __future__ import annotations

from aihr.contracts import CandidateProfile, YearMonth


def months_between(start: YearMonth, end: YearMonth) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month or 1) - (start.month or 1) + 1)


def enrich_profile(profile: CandidateProfile, today: YearMonth) -> CandidateProfile:
    positions = []
    total = 0
    known = False
    for pos in profile.positions:
        end = today if pos.is_current else pos.end
        if pos.start is not None and end is not None:
            duration = months_between(pos.start, end)
            pos = pos.model_copy(update={"duration_months": duration})
            total += duration
            known = True
        positions.append(pos)
    return profile.model_copy(
        update={"positions": positions, "total_experience_months": total if known else None}
    )
