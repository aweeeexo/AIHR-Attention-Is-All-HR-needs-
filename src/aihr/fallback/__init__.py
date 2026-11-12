"""Режим без LLM (T11). T00 — те же заглушки с decided_by="fallback"."""

from __future__ import annotations

from aihr.contracts import CandidateProfile, Document, Requirement, Verdict
from aihr.match.verify import attach_quotes
from aihr.retrieve import Retriever
from aihr.stubs import stub_profile, stub_requirements, stub_verdicts


def extract_requirements_fallback(vacancy: Document) -> list[Requirement]:
    return stub_requirements(vacancy)


def extract_profile_fallback(resume: Document) -> CandidateProfile:
    return stub_profile(resume)


def match_vacancy_fallback(
    reqs: list[Requirement],
    profile: CandidateProfile,
    resume: Document,
    retriever: Retriever,
) -> list[Verdict]:
    verdicts = stub_verdicts(reqs, resume, retriever, decided_by="fallback")
    return [attach_quotes(v, resume) for v in verdicts]
