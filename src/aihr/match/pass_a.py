"""Проход A (T07, шаги 1–3): все требования вакансии одним вызовом и шлюз кода поверх ответа.

Шлюз:
- несуществующие fragment_id удаляются; match / partial / mismatch без фрагментов → «Не указано»
  (D9) — это делает attach_quotes, он же подставляет цитаты из исходного текста (D8);
- adjacent → не выше partial (D15);
- indirect без цепочки вывода или с номерами не из fragment_ids → «Не указано» и в проход B;
- требование без вердикта модели → «Не указано».
"""

from __future__ import annotations

import logging
import re

from aihr.contracts import (
    STATUS_RU,
    CandidateProfile,
    Document,
    Evidence,
    EvidenceType,
    Fragment,
    Modality,
    ReqKind,
    Requirement,
    Status,
    Verdict,
)
from aihr.llm import LLMClient
from aihr.match.schemas import PassAResult, PassAVerdict
from aihr.match.verify import attach_quotes
from aihr.normalize import aliases
from aihr.normalize.tenure import format_months

log = logging.getLogger(__name__)

PROMPT_ID = "match/pass_a"
BATCH = 20  # требований в одном вызове; длинные вакансии идут пачками
MAX_COMMENT = 250

ROLE_RU = {
    "experience": "Опыт работы",
    "education": "Образование",
    "skills": "Навыки",
    "about": "О себе",
    "contacts": "Контакты",
    "other": "Прочее",
}
KIND_RU = {
    "skill": "навык",
    "experience": "опыт",
    "education": "образование",
    "language": "язык",
    "certificate": "сертификат",
    "soft": "личное качество",
    "duty": "обязанность",
    "other": "другое",
}
_REF = re.compile(r"\[([A-ZА-Я]\d+)\]")


def profile_summary(profile: CandidateProfile) -> str:
    lines = []
    for p in profile.positions:
        period = p.raw_dates or "даты не указаны"
        months = format_months(p.duration_months, p.dates_approximate)
        org = f", {p.organization}" if p.organization else ""
        lines.append(f"- {p.title}{org}: {period} = {months} ({', '.join(p.fragment_ids)})")
    if profile.total_experience_months is not None:
        lines.append(
            f"Общий стаж (без пересечений): {format_months(profile.total_experience_months)}"
        )
    for e in profile.education:
        level = e.level.value if e.level else "уровень не указан"
        place = e.institution or e.field or ""
        lines.append(f"- образование: {level}, {place} ({', '.join(e.fragment_ids)})")
    for lang in profile.languages:
        lines.append(
            f"- язык: {lang.name}, {lang.level_raw or 'уровень не указан'} "
            f"({', '.join(lang.fragment_ids)})"
        )
    return "\n".join(lines) or "мест работы и образования в профиле нет"


def requirements_block(reqs: list[Requirement]) -> str:
    lines = []
    for r in reqs:
        modality = "обязательное" if r.modality == Modality.must else "желательное"
        parts = [f"[{r.id}] ({modality}, {KIND_RU.get(r.kind.value, r.kind.value)}) {r.text}"]
        if r.alternatives:
            parts.append("достаточно одного из: " + "; ".join(r.alternatives))
        if r.threshold:
            t = r.threshold
            parts.append(
                f"порог: {t.kind.value} {t.value}" + (f" ({t.subject})" if t.subject else "")
            )
        if r.canonical_terms:
            terms = []
            for c in r.canonical_terms:
                names = aliases(c)[:6]
                terms.append(f"{c}: {', '.join(names)}" if names else c)
            parts.append("термины: " + "; ".join(terms))
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _for_prompt(fragments: list[Fragment]) -> list[Fragment]:
    out = []
    for f in fragments:
        role = ROLE_RU.get(f.section_role or "", "без раздела")
        out.append(f.model_copy(update={"masked_text": f"{{{role}}} {f.masked_text}"}))
    return out


def _not_stated(req: Requirement, comment: str, needs_review: bool = False) -> Verdict:
    return Verdict(
        requirement_id=req.id,
        status=Status.not_stated,
        comment=comment,
        confidence=0.5,
        decided_by="pass_a",
        needs_review=needs_review,
    )


def gate(req: Requirement, raw: PassAVerdict | None, resume: Document) -> Verdict:
    """Шлюз кода над ответом модели."""
    if raw is None:
        return _not_stated(req, "Модель не дала вердикт по этому требованию.", needs_review=True)
    known = {f.id for f in resume.fragments}
    ids = [fid for fid in dict.fromkeys(raw.fragment_ids) if fid in known]
    status, evidence_type = raw.status, raw.evidence_type
    needs_review = False

    if req.kind == ReqKind.soft and evidence_type in (EvidenceType.adjacent, EvidenceType.indirect):
        # Личное качество по смежным фактам не выводим (D43): это вопрос на интервью
        return _not_stated(
            req,
            "Личное качество прямо в резюме не подтверждено — уточнить на интервью.",
            needs_review=False,
        )
    if evidence_type == EvidenceType.adjacent and status == Status.match:
        status = Status.partial  # смежный навык — максимум «Частично» (D15)
    if evidence_type == EvidenceType.indirect:
        refs = set(_REF.findall(raw.inference or ""))
        if not raw.inference or not refs or not refs <= set(ids):
            log.info("%s: косвенный вывод без проверяемой цепочки → «Не указано»", req.id)
            return _not_stated(
                req,
                "Косвенный вывод модели не подтверждён ссылками на фрагменты.",
                needs_review=True,
            )
        needs_review = req.modality == Modality.must  # обязательное по косвенному — посмотреть

    verdict = Verdict(
        requirement_id=req.id,
        status=status,
        evidence_type=evidence_type if status != Status.not_stated else None,
        evidence=[Evidence(fragment_id=fid, quote="") for fid in ids],
        inference=raw.inference if evidence_type == EvidenceType.indirect else None,
        missing=raw.missing if status == Status.partial else None,
        comment=(raw.comment or STATUS_RU[status])[:MAX_COMMENT],
        confidence=raw.confidence,
        decided_by="pass_a",
        needs_review=needs_review,
    )
    return attach_quotes(verdict, resume)  # нет фрагмента → «Не указано», цитаты из текста


def pass_a(
    reqs: list[Requirement], profile: CandidateProfile, resume: Document, llm: LLMClient
) -> list[Verdict]:
    by_id: dict[str, PassAVerdict] = {}
    fragments = _for_prompt(resume.fragments)
    summary = profile_summary(profile)
    for start in range(0, len(reqs), BATCH):
        batch = reqs[start : start + BATCH]
        result = llm.structured(
            PROMPT_ID,
            {"profile": summary, "requirements": requirements_block(batch), "fragments": fragments},
            PassAResult,
        )
        wanted = {r.id for r in batch}
        for v in result.verdicts:
            if v.requirement_id in wanted and v.requirement_id not in by_id:
                by_id[v.requirement_id] = v
    return [gate(req, by_id.get(req.id), resume) for req in reqs]
