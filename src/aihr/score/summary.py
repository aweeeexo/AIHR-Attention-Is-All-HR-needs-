"""Итог рейтинга (D35, T08 шаг 8) — шаблоном из вердиктов, без LLM.

Если ни одна вакансия не подходит прямо, это валидный итог: говорим прямо, обосновываем
непокрытыми обязательными требованиями и показываем, куда кандидат мог бы подойти косвенно —
частичные, смежные и косвенные совпадения, с тем, чего не хватает.
"""

from __future__ import annotations

from aihr.contracts import (
    EvidenceType,
    FitLabel,
    Modality,
    Ranking,
    Requirement,
    Status,
    VacancyScore,
    Verdict,
)

LABEL_RU = {
    FitLabel.fits: "подходит",
    FitLabel.fits_with_caveats: "подходит с оговорками",
    FitLabel.not_fit: "не подходит",
}
MAX_ITEMS = 3


def _short(text: str, n: int = 70) -> str:
    text = " ".join(text.split()).rstrip(".")
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _name(s: VacancyScore) -> str:
    return f"«{_short(s.title or s.vacancy_id, 60)}» ({s.vacancy_id})"


def _unconfirmed(reqs: list[Requirement], verdicts: dict[str, Verdict]) -> list[str]:
    out = []
    for r in reqs:
        v = verdicts.get(r.id)
        if r.modality != Modality.must or not r.verifiable or v is None:
            continue
        if v.status == Status.mismatch:
            ids = ", ".join(e.fragment_id for e in v.evidence)
            out.append(f"{_short(r.text)} — по резюме не выполнено ({ids})")
        elif v.status == Status.not_stated:
            out.append(f"{_short(r.text)} — нет сведений")
    return out


def _indirect(reqs: list[Requirement], verdicts: dict[str, Verdict]) -> list[str]:
    """Косвенные основания: частичные, смежные и косвенные совпадения, сначала обязательные."""
    out = []
    for r in sorted(reqs, key=lambda x: x.modality != Modality.must):
        v = verdicts.get(r.id)
        if v is None or v.status not in (Status.partial, Status.match):
            continue
        if v.status == Status.match and v.evidence_type != EvidenceType.indirect:
            continue
        note = _short(r.text, 60)
        if v.evidence_type == EvidenceType.adjacent:
            note += " — смежный навык, закрывается обучением"
        elif v.evidence_type == EvidenceType.indirect:
            note += " — косвенно"
        if v.missing:
            note += f"; не хватает: {_short(v.missing, 60)}"
        out.append(note)
    return out


def ranking_summary(
    ranking: Ranking,
    requirements: dict[str, list[Requirement]],
    verdicts: dict[str, list[Verdict]],
) -> str:
    items = ranking.items
    if not items:
        return "Рейтинг не построен: нет ни одной обработанной вакансии."
    by_vac = {vid: {v.requirement_id: v for v in vs} for vid, vs in verdicts.items()}
    good = [s for s in items if s.label != FitLabel.not_fit]
    if good:
        best = good[0]
        text = (
            f"Лучше всего подходит {_name(best)}: {LABEL_RU[best.label]}, балл {best.score:g}, "
            f"закрыто {best.must.match} из {best.must.total} обязательных требований."
        )
        if len(good) > 1:
            text += (
                " Также: " + "; ".join(f"{_name(s)} — {LABEL_RU[s.label]}" for s in good[1:]) + "."
            )
        return text

    parts = ["Прямо не подходит ни одна вакансия."]
    for s in items:
        reasons = _unconfirmed(requirements.get(s.vacancy_id, []), by_vac.get(s.vacancy_id, {}))
        if reasons:
            parts.append(f"{_name(s)}: " + "; ".join(reasons[:MAX_ITEMS]) + ".")
    candidates = []
    for s in items:  # уже по убыванию балла
        notes = _indirect(requirements.get(s.vacancy_id, []), by_vac.get(s.vacancy_id, {}))
        if notes:
            candidates.append(f"{_name(s)}, балл {s.score:g}: " + "; ".join(notes[:MAX_ITEMS]))
    if candidates:
        parts.append("Косвенно мог бы подойти: " + " | ".join(candidates) + ".")
    else:
        parts.append("Косвенных совпадений по требованиям нет.")
    return " ".join(parts)
