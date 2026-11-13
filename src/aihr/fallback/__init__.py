"""Режим без LLM (T11): та же структура MatchResult, mode="fallback", результат скромнее.

Без LLM «Не соответствует» ставит только код по порогу (стаж, образование, язык), остальное
неуверенное — «Не указано» (D9). Включается при LLM_PROVIDER=none или когда LLM недоступна.
"""

from __future__ import annotations

from aihr.contracts import CandidateProfile, Document, Requirement, Verdict
from aihr.fallback.matching import match_vacancy_fallback as _match
from aihr.fallback.profile import extract_profile_fallback
from aihr.fallback.requirements import extract_requirements_fallback
from aihr.match.verify import attach_quotes
from aihr.retrieve import Retriever

__all__ = ["extract_profile_fallback", "extract_requirements_fallback", "match_vacancy_fallback"]


def match_vacancy_fallback(
    reqs: list[Requirement],
    profile: CandidateProfile,
    resume: Document,
    retriever: Retriever,
) -> list[Verdict]:
    return [attach_quotes(v, resume) for v in _match(reqs, profile, resume, retriever)]
