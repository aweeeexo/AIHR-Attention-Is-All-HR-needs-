"""Сопоставление требований с резюме (D6, T07): проход A + шлюз кода, правила — rules.py."""

from __future__ import annotations

from aihr.contracts import CandidateProfile, Document, Requirement, Verdict
from aihr.llm import LLMClient
from aihr.match.pass_a import pass_a
from aihr.match.rules import apply_rules
from aihr.match.verify import attach_quotes
from aihr.retrieve import Retriever

__all__ = ["apply_rules", "attach_quotes", "match_vacancy"]


def match_vacancy(
    reqs: list[Requirement],
    profile: CandidateProfile,
    resume: Document,
    retriever: Retriever,
    llm: LLMClient,
) -> list[Verdict]:
    if not reqs:
        return []
    return pass_a(reqs, profile, resume, llm)
