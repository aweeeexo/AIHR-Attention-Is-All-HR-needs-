"""Извлечение: требования вакансии (T04) и профиль кандидата (T05; пока заглушка)."""

from __future__ import annotations

from aihr.contracts import CandidateProfile, Document
from aihr.extract.requirements import extract_requirements
from aihr.llm import LLMClient
from aihr.stubs import stub_profile

__all__ = ["extract_profile", "extract_requirements"]


def extract_profile(resume: Document, llm: LLMClient) -> CandidateProfile:
    return stub_profile(resume)
