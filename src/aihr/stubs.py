"""Правдоподобные данные-заглушки для каркаса (T00). Смысла в них нет, но структура валидна:
id фрагментов настоящие, цитаты подставляет код, по одному вердикту каждого статуса.

Удаляем по мере готовности: требования — T04, профиль — T05, сопоставление — T07, fallback — T11.
"""

from __future__ import annotations

from typing import Literal

from aihr.contracts import (
    CandidateProfile,
    Document,
    Evidence,
    EvidenceType,
    MentionType,
    Modality,
    Position,
    ReqKind,
    Requirement,
    SkillMention,
    Status,
    Threshold,
    ThresholdKind,
    Verdict,
)
from aihr.retrieve import Retriever

STUB_STATUSES = [Status.match, Status.partial, Status.mismatch, Status.not_stated]

_REQ_SHAPES: list[tuple[ReqKind, Modality, Threshold | None]] = [
    (ReqKind.skill, Modality.must, None),
    (ReqKind.duty, Modality.nice, None),  # обязанность всегда nice (D3)
    (ReqKind.experience, Modality.must, Threshold(kind=ThresholdKind.years, value="3")),
    (ReqKind.skill, Modality.nice, None),
]


def stub_requirements(vacancy: Document) -> list[Requirement]:
    # Первый фрагмент обычно название должности — требования берём из следующих
    frags = vacancy.fragments[1:] or vacancy.fragments
    reqs = []
    for i, (kind, modality, threshold) in enumerate(_REQ_SHAPES):
        frag = frags[i % len(frags)]
        reqs.append(
            Requirement(
                id=f"{vacancy.id}.req{i + 1}",
                vacancy_id=vacancy.id,
                text=frag.text[:200],
                kind=kind,
                modality=modality,
                modality_marker=None,
                modality_reason="заглушка T00",
                threshold=threshold,
                source_fragment_ids=[frag.id],
            )
        )
    return reqs


def stub_profile(resume: Document) -> CandidateProfile:
    first = resume.fragments[0]
    second = resume.fragments[min(1, len(resume.fragments) - 1)]
    return CandidateProfile(
        positions=[
            Position(
                title="Должность (заглушка)",
                organization=None,
                start=None,
                end=None,
                raw_dates=None,
                fragment_ids=[first.id],
            )
        ],
        skills=[
            SkillMention(
                name="Навык (заглушка)",
                mention_type=MentionType.listed_only,
                fragment_ids=[second.id],
            )
        ],
    )


def stub_verdicts(
    reqs: list[Requirement],
    resume: Document,
    retriever: Retriever,
    decided_by: Literal["pass_a", "pass_b", "rule", "fallback"],
) -> list[Verdict]:
    verdicts = []
    for i, req in enumerate(reqs):
        status = STUB_STATUSES[i % len(STUB_STATUSES)]
        evidence: list[Evidence] = []
        if status != Status.not_stated:
            hits = retriever.search(req.text, [], k=1)
            fid = hits[0][0] if hits else resume.fragments[i % len(resume.fragments)].id
            evidence = [Evidence(fragment_id=fid, quote="")]  # цитату подставит код
        verdicts.append(
            Verdict(
                requirement_id=req.id,
                status=status,
                evidence_type=EvidenceType.direct if evidence else None,
                evidence=evidence,
                missing="заглушка: чего не хватает" if status == Status.partial else None,
                comment="Заглушка T00: статус выбран по порядку, а не по смыслу.",
                confidence=0.5,
                partial_value=None,
                decided_by=decided_by,
            )
        )
    return verdicts
