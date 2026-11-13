"""Сопоставление требований с резюме (D6, T07): проход A, проход B для спорных, шлюз кода.

Правила порогов (rules.py) применяет пайплайн поверх результата.
"""

from __future__ import annotations

from aihr.contracts import CandidateProfile, Document, Requirement, Verdict
from aihr.llm import LLMClient
from aihr.match.pass_a import pass_a
from aihr.match.pass_b import pass_b
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
    verdicts = pass_a(reqs, profile, resume, llm)
    return pass_b(reqs, verdicts, profile, resume, retriever, llm)
