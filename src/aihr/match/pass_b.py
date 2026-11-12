"""Проход B (T07, шаги 5–6): узкий вопрос по одному спорному требованию с поиском доказательств.

Спорные: обязательные «Не соответствует» / «Не указано» (ошибка здесь дороже всего), затем
«Частично», низкая уверенность и вердикты с needs_review. Не больше MAX_PER_VACANCY вызовов.
Ответ проходит тот же шлюз, что и проход A. A и B не согласны → needs_review.
"""

from __future__ import annotations

import logging

from aihr.contracts import (
    STATUS_RU,
    CandidateProfile,
    Document,
    LLMBadOutput,
    LLMUnavailable,
    Modality,
    PrivacyViolation,
    Requirement,
    Status,
    Verdict,
)
from aihr.llm import LLMClient
from aihr.match.pass_a import ROLE_RU, gate, profile_summary
from aihr.match.schemas import PassAVerdict
from aihr.normalize import aliases
from aihr.retrieve import Retriever, roles_for

log = logging.getLogger(__name__)

PROMPT_ID = "match/pass_b"
MAX_PER_VACANCY = 8
LOW_CONFIDENCE = 0.7
K = 8


def disputed(reqs: list[Requirement], verdicts: list[Verdict]) -> list[tuple[Requirement, Verdict]]:
    """Спорные требования в порядке важности: сначала обязательные без подтверждения."""
    by_id = {r.id: r for r in reqs}
    scored: list[tuple[int, int, Requirement, Verdict]] = []
    for i, v in enumerate(verdicts):
        req = by_id.get(v.requirement_id)
        if req is None or not req.verifiable:
            continue
        must = req.modality == Modality.must
        if must and v.status in (Status.mismatch, Status.not_stated):
            priority = 0
        elif v.needs_review:
            priority = 1
        elif v.status == Status.partial:
            priority = 2 if must else 3
        elif v.confidence < LOW_CONFIDENCE and v.status != Status.not_stated:
            priority = 4
        else:
            continue
        scored.append((priority, i, req, v))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [(req, v) for _, _, req, v in scored[:MAX_PER_VACANCY]]


def _previous(v: Verdict) -> str:
    ids = ", ".join(e.fragment_id for e in v.evidence) or "нет"
    return f"{STATUS_RU[v.status]} (фрагменты: {ids}). {v.comment}"


def ask(
    req: Requirement,
    previous: Verdict,
    profile: CandidateProfile,
    resume: Document,
    retriever: Retriever,
    llm: LLMClient,
) -> Verdict:
    terms = [*req.canonical_terms, *(a for c in req.canonical_terms for a in aliases(c)[:4])]
    query = " ".join(
        [req.text, *req.alternatives, (req.threshold.subject or "") if req.threshold else ""]
    )
    hits = retriever.search(query, terms, k=K, section_roles=roles_for(req.kind))
    ids = [fid for fid, _ in hits]
    ids += [e.fragment_id for e in previous.evidence if e.fragment_id not in ids]
    by_id = {f.id: f for f in resume.fragments}
    fragments = [
        by_id[fid].model_copy(
            update={
                "masked_text": f"{{{ROLE_RU.get(by_id[fid].section_role or '', 'без раздела')}}} "
                f"{by_id[fid].masked_text}"
            }
        )
        for fid in sorted(set(ids), key=lambda x: by_id[x].order)
        if fid in by_id
    ]
    if not fragments:  # поиск ничего не нашёл — подтверждения в резюме нет
        return previous
    raw = llm.structured(
        PROMPT_ID,
        {
            "req_id": req.id,
            "requirement": req.text,
            "profile": profile_summary(profile),
            "previous": _previous(previous),
            "fragments": fragments,
        },
        PassAVerdict,
    )
    return gate(req, raw.model_copy(update={"requirement_id": req.id}), resume)


def pass_b(
    reqs: list[Requirement],
    verdicts: list[Verdict],
    profile: CandidateProfile,
    resume: Document,
    retriever: Retriever,
    llm: LLMClient,
) -> list[Verdict]:
    result = {v.requirement_id: v for v in verdicts}
    for req, previous in disputed(reqs, verdicts):
        try:
            new = ask(req, previous, profile, resume, retriever, llm)
        except (LLMBadOutput, PrivacyViolation) as exc:
            log.warning("%s: проход B не дал валидного ответа (%s), остаётся проход A", req.id, exc)
            continue
        except LLMUnavailable as exc:
            # Вердикты прохода A уже есть — не теряем их из-за сбоя на уточнении
            log.warning("проход B прерван, LLM недоступна (%s): остаются вердикты прохода A", exc)
            break
        if new is previous:
            continue
        changed = new.status != previous.status
        comment = new.comment
        if changed:
            comment = (
                f"{comment} Проходы разошлись ({STATUS_RU[previous.status]} → "
                f"{STATUS_RU[new.status]}) — проверить вручную."
            )
        result[req.id] = new.model_copy(
            update={
                "decided_by": "pass_b",
                "needs_review": new.needs_review or changed,
                "comment": comment[:250],
            }
        )
    return [result[v.requirement_id] for v in verdicts]
