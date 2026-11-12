"""Тексты от LLM с проверкой сущностей (T09, шаги 5 и 8; T07, шаг 9).

Модель получает только проверенные факты. Сущность ответа, которой нет в фактах, — повтор с
указанием на ошибку, затем откат к шаблону. LLM недоступна — сразу шаблон.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from aihr.contracts import (
    STATUS_RU,
    Document,
    LLMBadOutput,
    LLMUnavailable,
    MentionType,
    Modality,
    Point,
    PrivacyViolation,
    Question,
    Requirement,
    Status,
    Verdict,
)
from aihr.llm import LLMClient
from aihr.report.entities import entities, has_stop_phrase, unverified

log = logging.getLogger(__name__)

MAX_QUESTIONS = 7
MAX_BEYOND = 5
_LLM_ERRORS = (LLMUnavailable, LLMBadOutput, PrivacyViolation)


@dataclass
class EntityStats:
    total: int = 0
    unverified: int = 0
    notes: list[str] = field(default_factory=list)


# ---------- вопросы ----------


class GeneratedQuestion(BaseModel):
    requirement_id: str
    text: str
    kind: Literal["factual", "behavioral"]
    why: str


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion]


def question_sources(
    reqs: list[Requirement], verdicts: dict[str, Verdict], profile_listed: set[str]
) -> list[Requirement]:
    """Что уточнять: обязательные «Не указано» и «Частично», навыки только из списка, непроверяемые.
    Порядок — по весу: обязательные первыми."""
    picked = []
    for req in reqs:
        v = verdicts.get(req.id)
        if v is None:
            continue
        listed = bool(set(req.canonical_terms) & profile_listed)
        if (
            (req.modality == Modality.must and v.status in (Status.not_stated, Status.partial))
            or (listed and v.status == Status.match)
            or (not req.verifiable and req.modality == Modality.must)
            or v.status == Status.mismatch
        ):
            picked.append(req)
    picked.sort(key=lambda r: (r.modality != Modality.must, not r.verifiable))
    return picked[:MAX_QUESTIONS]


def _facts_line(req: Requirement, v: Verdict) -> str:
    parts = [f"[{req.id}] {req.text}", f"статус: {STATUS_RU[v.status]}"]
    if v.missing:
        parts.append(f"не хватает: {v.missing}")
    if not req.verifiable:
        parts.append("по резюме не проверяется")
    parts.append(f"комментарий: {v.comment}")
    return " | ".join(parts)


def template_question(req: Requirement, v: Verdict) -> Question:
    if not req.verifiable:
        return Question(
            requirement_id=req.id,
            kind="behavioral",
            text=f"Расскажите о ситуации из работы, где проявилось: {req.text.rstrip('.')}.",
            why="по резюме не проверяется",
        )
    if v.status == Status.partial:
        tail = f" В резюме: {v.missing}." if v.missing else ""
        return Question(
            requirement_id=req.id,
            kind="factual",
            text=f"Уточните, пожалуйста, ваш опыт: {req.text.rstrip('.')}.{tail}",
            why="требование подтверждено частично",
        )
    if v.status == Status.match:
        return Question(
            requirement_id=req.id,
            kind="factual",
            text=f"Где и в каких задачах вы применяли: {req.text.rstrip('.')}?",
            why="навык указан в списке, но не описан в опыте",
        )
    if v.status == Status.mismatch:
        return Question(
            requirement_id=req.id,
            kind="factual",
            text=f"Есть ли у вас что-то, что закрывает требование: {req.text.rstrip('.')}?",
            why="по резюме требование не выполнено",
        )
    return Question(
        requirement_id=req.id,
        kind="factual",
        text=f"Есть ли у вас опыт: {req.text.rstrip('.')}? Как долго и в каких задачах?",
        why="в резюме нет сведений",
    )


def questions(
    reqs: list[Requirement],
    verdicts: dict[str, Verdict],
    profile_listed: set[str],
    llm: LLMClient | None,
    stats: EntityStats,
) -> list[Question]:
    sources = question_sources(reqs, verdicts, profile_listed)
    if not sources:
        return []
    templates = {r.id: template_question(r, verdicts[r.id]) for r in sources}
    if llm is None or not llm.available:
        return list(templates.values())
    facts = "\n".join(_facts_line(r, verdicts[r.id]) for r in sources)
    correction = ""
    for _ in range(2):
        try:
            result = llm.structured(
                "report/questions", {"items": facts, "correction": correction}, GeneratedQuestions
            )
        except _LLM_ERRORS as exc:
            log.warning("вопросы: LLM недоступна (%s), шаблоны", type(exc).__name__)
            return list(templates.values())
        out: dict[str, Question] = {}
        bad: list[str] = []
        for q in result.questions:
            if q.requirement_id not in templates or q.requirement_id in out:
                continue
            missing = unverified(q.text, facts)
            if missing or has_stop_phrase(q.text):
                bad += missing or ["оценочная формулировка"]
                continue
            out[q.requirement_id] = Question(
                requirement_id=q.requirement_id, text=q.text.strip(), kind=q.kind, why=q.why.strip()
            )
        if not bad:
            break
        correction = ", ".join(dict.fromkeys(bad))
    if bad:  # непроверенный вопрос в отчёт не попадает — его место занимает шаблон
        stats.notes.append(f"вопросы: заменены шаблоном из-за сущностей {correction}")
    for q in out.values():
        stats.total += len(entities(q.text))
    return [out.get(r.id) or templates[r.id] for r in sources]


# ---------- сверх требований (позиция кандидата, D7) ----------


class BeyondItem(BaseModel):
    text: str
    fragment_ids: list[str] = Field(min_length=1)


class BeyondResult(BaseModel):
    items: list[BeyondItem]


def beyond_requirements(
    reqs: list[Requirement],
    verdicts: dict[str, Verdict],
    resume: Document,
    llm: LLMClient | None,
    stats: EntityStats,
) -> list[Point]:
    if llm is None or not llm.available:
        return []
    from aihr.match.pass_a import ROLE_RU

    lines = [
        f"[{r.id}] {r.text} — {STATUS_RU[verdicts[r.id].status]}" for r in reqs if r.id in verdicts
    ]
    fragments = [
        f.model_copy(
            update={
                "masked_text": f"{{{ROLE_RU.get(f.section_role or '', 'без раздела')}}} "
                f"{f.masked_text}"
            }
        )
        for f in resume.fragments
    ]
    try:
        result = llm.structured(
            "report/candidate_side",
            {"requirements": "\n".join(lines), "fragments": fragments},
            BeyondResult,
        )
    except _LLM_ERRORS as exc:
        log.warning("сверх требований: LLM недоступна (%s)", type(exc).__name__)
        return []
    by_id = {f.id: f for f in resume.fragments}
    out = []
    for item in result.items[:MAX_BEYOND]:
        ids = [fid for fid in dict.fromkeys(item.fragment_ids) if fid in by_id]
        if not ids or has_stop_phrase(item.text):
            continue
        facts = " ".join(by_id[f].masked_text or by_id[f].text for f in ids)
        missing = unverified(item.text, facts)
        if missing:
            stats.notes.append(
                f"сверх требований: пункт отброшен, нет в фрагментах: {', '.join(missing)}"
            )
            continue
        stats.total += len(entities(item.text))
        out.append(Point(text=item.text.strip(), fragment_ids=ids))
    return out


def listed_only_terms(profile) -> set[str]:
    return {
        s.canonical
        for s in profile.skills
        if s.canonical and s.mention_type == MentionType.listed_only
    }
