"""Извлечение: требования вакансии (T04) и профиль кандидата (T05). T00 — заглушки."""

from __future__ import annotations

from aihr.contracts import CandidateProfile, Document, Requirement
from aihr.llm import LLMClient
from aihr.stubs import stub_profile, stub_requirements


def extract_requirements(vacancy: Document, llm: LLMClient) -> list[Requirement]:
    return stub_requirements(vacancy)


def extract_profile(resume: Document, llm: LLMClient) -> CandidateProfile:
    return stub_profile(resume)
