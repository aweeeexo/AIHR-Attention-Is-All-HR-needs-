"""Сопоставление требований с резюме (D6, T07). T00 — заглушка + настоящая проверка цитат."""

from __future__ import annotations

from aihr.contracts import CandidateProfile, Document, Requirement, Verdict
from aihr.llm import LLMClient
from aihr.match.rules import apply_rules
from aihr.match.verify import attach_quotes
from aihr.retrieve import Retriever
from aihr.stubs import stub_verdicts

__all__ = ["apply_rules", "attach_quotes", "match_vacancy"]


def match_vacancy(
    reqs: list[Requirement],
    profile: CandidateProfile,
    resume: Document,
    retriever: Retriever,
    llm: LLMClient,
) -> list[Verdict]:
    verdicts = stub_verdicts(reqs, resume, retriever, decided_by="pass_a")
    return [attach_quotes(v, resume) for v in verdicts]
