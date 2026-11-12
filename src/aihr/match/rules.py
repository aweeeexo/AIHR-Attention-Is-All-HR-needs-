"""Правила поверх LLM: стаж, пороги, уровни (D13, T07 шаг 4). T00 — без изменений."""

from __future__ import annotations

from aihr.contracts import CandidateProfile, Requirement, Verdict


def apply_rules(req: Requirement, verdict: Verdict, profile: CandidateProfile) -> Verdict:
    return verdict
