"""Балл и рейтинг считает код (D11). T00 — базовая формула из T08, T08 доводит объяснения.

S = 100 · Σ wᵢ·vᵢ / Σ wᵢ, где v = 1 (соответствует), p (частично), 0 (не соответствует),
u (не указано). Основной балл при u = 0.5, интервал — при u = 0 и u = 1 (D5).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from aihr.config import get_settings
from aihr.contracts import (
    Document,
    FitLabel,
    Modality,
    Ranking,
    Requirement,
    Status,
    StatusCounts,
    VacancyScore,
    Verdict,
)

TOP_N = 3


@dataclass(frozen=True)
class ScoringConfig:
    w_must: float
    w_nice: float
    partial_default: float
    unknown_value: float
    fits_min_score: float
    fits_max_blocking_gaps: int
    caveats_min_score: float


def load_scoring_config(path: Path | None = None) -> ScoringConfig:
    return _load_scoring_config(Path(path or get_settings().scoring_config).resolve())


@lru_cache
def _load_scoring_config(path: Path) -> ScoringConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    labels = raw["labels"]
    return ScoringConfig(
        w_must=float(raw["weights"]["must"]),
        w_nice=float(raw["weights"]["nice"]),
        partial_default=float(raw["partial_default"]),
        unknown_value=float(raw["unknown_value"]),
        fits_min_score=float(labels["fits"]["min_score"]),
        fits_max_blocking_gaps=int(labels["fits"].get("max_blocking_gaps", 0)),
        caveats_min_score=float(labels["fits_with_caveats"]["min_score"]),
    )


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """plural(5, ("пункт", "пункта", "пунктов")) → «пунктов»."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    if n % 10 == 1:
        return forms[0]
    if 2 <= n % 10 <= 4:
        return forms[1]
    return forms[2]


def _value(status: Status, partial_value: float | None, cfg: ScoringConfig, u: float) -> float:
    if status == Status.match:
        return 1.0
    if status == Status.partial:
        return partial_value if partial_value is not None else cfg.partial_default
    if status == Status.mismatch:
        return 0.0
    return u


def _count(items: list[tuple[Requirement, Status]], modality: Modality) -> StatusCounts:
    counts = StatusCounts()
    for req, status in items:
        if req.modality != modality:
            continue
        counts.total += 1
        setattr(counts, status.value, getattr(counts, status.value) + 1)
    return counts


def score_vacancy(
    vacancy: Document, reqs: list[Requirement], verdicts: list[Verdict]
) -> VacancyScore:
    cfg = load_scoring_config()
    by_req = {v.requirement_id: v for v in verdicts}
    rows: list[tuple[Requirement, Status, float | None, float]] = []
    for req in reqs:
        v = by_req.get(req.id)
        status = v.status if v else Status.not_stated  # нет вердикта — нет сведений
        weight = cfg.w_must if req.modality == Modality.must else cfg.w_nice
        rows.append((req, status, v.partial_value if v else None, weight))

    def total(u: float) -> float:
        w_sum = sum(w for *_, w in rows)
        if not w_sum:
            return 0.0
        return round(100 * sum(w * _value(s, p, cfg, u) for _, s, p, w in rows) / w_sum, 1)

    score = total(cfg.unknown_value)
    pairs = [(req, status) for req, status, _, _ in rows]
    must, nice = _count(pairs, Modality.must), _count(pairs, Modality.nice)
    blocking = [
        req.id
        for req, status in pairs
        if req.modality == Modality.must and status == Status.mismatch
    ]

    if score >= cfg.fits_min_score and len(blocking) <= cfg.fits_max_blocking_gaps:
        label = FitLabel.fits
    elif score >= cfg.caveats_min_score:
        label = FitLabel.fits_with_caveats
    else:
        label = FitLabel.not_fit

    contrib = [(req.id, w * _value(s, p, cfg, cfg.unknown_value), w) for req, s, p, w in rows]
    top_plus = [rid for rid, c, _ in sorted(contrib, key=lambda x: -x[1]) if c > 0][:TOP_N]
    top_minus = [rid for rid, c, w in sorted(contrib, key=lambda x: x[1] - x[2]) if w - c > 0][
        :TOP_N
    ]

    score_min, score_max = total(0.0), total(1.0)
    unknown = must.not_stated + nice.not_stated
    parts = [
        f"Закрыто {must.match} из {must.total} обязательных и {nice.match} из {nice.total} "
        f"желательных требований."
    ]
    if unknown:
        parts.append(
            f"Не указано {unknown} {plural(unknown, ('требование', 'требования', 'требований'))}, "
            f"поэтому балл от {score_min:g} до {score_max:g}."
        )
    if blocking:
        parts.append(f"Обязательные требования без соответствия: {', '.join(blocking)}.")

    return VacancyScore(
        vacancy_id=vacancy.id,
        title=vacancy.title,
        score=score,
        score_min=score_min,
        score_max=score_max,
        must=must,
        nice=nice,
        blocking_gaps=blocking,
        label=label,
        top_plus=top_plus,
        top_minus=top_minus,
        explanation=" ".join(parts),
    )


def _must_share(s: VacancyScore) -> float:
    return s.must.match / s.must.total if s.must.total else 0.0


def rank(scores: list[VacancyScore]) -> Ranking:
    cfg = load_scoring_config()
    items = sorted(
        scores,
        key=lambda s: (
            -s.score,
            -_must_share(s),
            s.must.not_stated + s.nice.not_stated,
            s.vacancy_id,
        ),
    )
    comparison = []
    for upper, lower in itertools.pairwise(items):
        diff = round(upper.score - lower.score)
        head = (
            f"{upper.vacancy_id} выше {lower.vacancy_id} на {diff} "
            f"{plural(diff, ('пункт', 'пункта', 'пунктов'))}"
            if diff
            else f"{upper.vacancy_id} и {lower.vacancy_id} наравне по баллу"
        )
        comparison.append(
            f"{head}: обязательных закрыто {upper.must.match} из {upper.must.total} "
            f"против {lower.must.match} из {lower.must.total}."
        )
    formula = (
        "S = 100 · Σ w·v / Σ w. Веса: обязательное "
        f"{cfg.w_must:g}, желательное {cfg.w_nice:g}. v: соответствует 1, частично "
        f"{cfg.partial_default:g} (или доля порога), не соответствует 0, не указано "
        f"{cfg.unknown_value:g}; интервал — при «не указано» = 0 и = 1."
    )
    return Ranking(
        items=items,
        best_vacancy_id=items[0].vacancy_id if items else None,
        comparison=comparison,
        formula=formula,
    )
