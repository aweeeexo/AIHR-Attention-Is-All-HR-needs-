"""Части отчёта, которые собирает код (T09, шаги 1–4): таблица, сильные стороны, пробелы, риски."""

from __future__ import annotations

import re

from aihr.contracts import (
    STATUS_RU,
    CandidateProfile,
    Document,
    EvidenceType,
    MentionType,
    Modality,
    Point,
    Requirement,
    RequirementRow,
    Status,
    ThresholdKind,
    Verdict,
    YearMonth,
)
from aihr.normalize.tenure import format_months, tenure_for

OLD_SKILL_YEARS = 5
_ROW_ORDER = {Status.mismatch: 0, Status.partial: 1, Status.not_stated: 2, Status.match: 3}
_NUMBER = re.compile(r"\d")


def _quote(doc: Document, ids: list[str]) -> str:
    by_id = {f.id: f.text for f in doc.fragments}
    return " … ".join(by_id[f] for f in ids if f in by_id)


def _short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def rows(
    vacancy: Document, reqs: list[Requirement], verdicts: dict[str, Verdict]
) -> list[RequirementRow]:
    """Сначала обязательные; внутри — то, что требует внимания: «Не соответствует», «Частично»…"""
    ordered = sorted(
        reqs,
        key=lambda r: (
            r.modality != Modality.must,
            _ROW_ORDER[verdicts[r.id].status if r.id in verdicts else Status.not_stated],
        ),
    )
    out = []
    for req in ordered:
        v = verdicts.get(req.id)
        status = v.status if v else Status.not_stated
        comment = v.comment if v else "Вердикт не получен."
        if v and v.needs_review:
            comment = f"{comment} (стоит проверить вручную)"
        out.append(
            RequirementRow(
                requirement_id=req.id,
                requirement=req.text,
                modality=req.modality,
                vacancy_quote=_quote(vacancy, req.source_fragment_ids),
                resume_evidence=v.evidence if v else [],
                status=status,
                status_ru=STATUS_RU[status],
                evidence_type=v.evidence_type if v else None,
                comment=comment,
                computed=v.computed if v else None,
            )
        )
    return out


def _positions_for(profile: CandidateProfile, v: Verdict):
    ids = {e.fragment_id for e in v.evidence}
    return [p for p in profile.positions if ids & set(p.fragment_ids)]


def strengths(
    reqs: list[Requirement], verdicts: dict[str, Verdict], profile: CandidateProfile
) -> list[Point]:
    out: list[Point] = []
    matched = [r for r in reqs if (v := verdicts.get(r.id)) and v.status == Status.match]
    matched.sort(
        key=lambda r: (
            r.modality != Modality.must,
            verdicts[r.id].evidence_type != EvidenceType.direct,
        )
    )
    for req in matched:
        v = verdicts[req.id]
        ids = [e.fragment_id for e in v.evidence]
        text = f"Подтверждено: {_short(req.text)}"
        if v.evidence_type == EvidenceType.indirect and v.inference:
            text += f" (косвенно: {_short(v.inference, 120)})"
        t = req.threshold
        if t and t.kind == ThresholdKind.years:
            positions = _positions_for(profile, v) if t.subject else profile.positions
            months, approx = tenure_for(positions)
            try:
                need = float(t.value)
            except ValueError:
                need = 0
            if months is not None and need and months / 12 >= 1.5 * need:
                text = (
                    f"Опыт с запасом: {format_months(months, approx)} при требуемых {t.value} "
                    f"({_short(req.text, 60)})"
                )
        out.append(Point(text=text, requirement_ids=[req.id], fragment_ids=ids))

    seen: set[str] = set()
    for req in matched:
        for p in _positions_for(profile, verdicts[req.id]):
            for ach in p.achievements:
                if _NUMBER.search(ach) and ach not in seen:
                    seen.add(ach)
                    out.append(
                        Point(
                            text=f"Достижение: {_short(ach, 140)}",
                            requirement_ids=[req.id],
                            fragment_ids=p.fragment_ids,
                        )
                    )
    return out


def gaps(reqs: list[Requirement], verdicts: dict[str, Verdict]) -> list[Point]:
    blocking: list[Point] = []
    partial: list[Point] = []
    for req in reqs:
        v = verdicts.get(req.id)
        if v is None or req.modality != Modality.must:
            continue
        ids = [e.fragment_id for e in v.evidence]
        if v.status == Status.mismatch:
            blocking.append(
                Point(
                    text=f"Не соответствует обязательному требованию: {_short(req.text)}",
                    requirement_ids=[req.id],
                    fragment_ids=ids,
                )
            )
        elif v.status == Status.partial:
            text = f"Частично: {_short(req.text)}"
            if v.missing:
                text += f" — {v.missing}"
            if v.evidence_type == EvidenceType.adjacent:
                text += " (смежный навык, закрывается обучением)"
            partial.append(Point(text=text, requirement_ids=[req.id], fragment_ids=ids))
    return blocking + partial


def risks(
    reqs: list[Requirement],
    verdicts: dict[str, Verdict],
    profile: CandidateProfile,
    today: YearMonth,
) -> list[Point]:
    out: list[Point] = []
    by_id = {r.id: r for r in reqs}
    for req in reqs:
        v = verdicts.get(req.id)
        if v is None:
            continue
        ids = [e.fragment_id for e in v.evidence]
        if req.modality == Modality.must and v.status == Status.not_stated and req.verifiable:
            out.append(
                Point(
                    text=f"Стоит уточнить: в резюме нет сведений — {_short(req.text)}",
                    requirement_ids=[req.id],
                )
            )
        if v.needs_review and v.status != Status.not_stated:
            reason = (
                "вывод косвенный"
                if v.evidence_type == EvidenceType.indirect
                else "проверки разошлись"
            )
            out.append(
                Point(
                    text=f"Стоит уточнить ({reason}): {_short(req.text)}",
                    requirement_ids=[req.id],
                    fragment_ids=ids,
                )
            )

    # навыки из требований, которые есть только в списке навыков или давно не использовались
    terms = {t: r.id for r in by_id.values() for t in r.canonical_terms}
    for skill in profile.skills:
        rid = terms.get(skill.canonical or "")
        if rid is None or verdicts.get(rid) is None or verdicts[rid].status == Status.not_stated:
            continue
        if skill.mention_type == MentionType.listed_only:
            out.append(
                Point(
                    text=f"Стоит уточнить: «{skill.name}» указан только в списке навыков, "
                    "без описания опыта",
                    requirement_ids=[rid],
                    fragment_ids=skill.fragment_ids,
                )
            )
        elif skill.last_used_year and today.year - skill.last_used_year > OLD_SKILL_YEARS:
            out.append(
                Point(
                    text=f"Стоит уточнить: «{skill.name}» последний раз — в "
                    f"{skill.last_used_year} году",
                    requirement_ids=[rid],
                    fragment_ids=skill.fragment_ids,
                )
            )
    for start, end in profile.gaps_months:
        out.append(
            Point(
                text=f"Стоит уточнить: перерыв в работе с {start.month or 1:02d}.{start.year} "
                f"по {end.month or 1:02d}.{end.year}"
            )
        )
    return out
