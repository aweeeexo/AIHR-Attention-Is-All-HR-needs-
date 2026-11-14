"""Балл и рейтинг считает код (D11). Одна формула и одни веса для всех вакансий (критерий 3).

S = 100 · Σ wᵢ·vᵢ / Σ wᵢ, где v = 1 (соответствует), p (частично), 0 (не соответствует),
u (не указано). Основной балл при u = 0.5, интервал — при u = 0 и u = 1 (D5).
Нокаута нет (D4): обязательное «не соответствует» → blocking_gaps, метка не «подходит».
Личные качества (kind = soft) весят w_soft даже как обязательные и не влияют на метку (D55):
люди редко пишут их в резюме, а проверяются они на собеседовании.
Объяснения собирает шаблон из чисел и текстов требований, без LLM.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import yaml

from aihr.config import get_settings
from aihr.contracts import (
    Document,
    FitLabel,
    Modality,
    Ranking,
    ReqKind,
    Requirement,
    Status,
    StatusCounts,
    VacancyScore,
    Verdict,
)

TOP_N = 3
SHORT = 70  # длина текста требования в объяснении


@dataclass(frozen=True)
class ScoringConfig:
    w_must: float
    w_nice: float
    partial_default: float
    unknown_value: float
    fits_min_score: float
    fits_max_blocking_gaps: int
    caveats_min_score: float
    close_margin: float = 3.0  # D40
    caveats_min_confirmed: float = 0.5  # D41
    w_soft: float = 1.0  # D55: личные качества

    def with_changes(self, **kw: float) -> ScoringConfig:
        return replace(self, **kw)  # type: ignore[arg-type]


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
        close_margin=float(raw.get("close_margin", 3)),
        caveats_min_confirmed=float(labels["fits_with_caveats"].get("min_confirmed", 0.5)),
        w_soft=float(raw["weights"].get("soft", raw["weights"]["nice"])),
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


_REQ = ("требование", "требования", "требований")


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= SHORT else text[: SHORT - 1].rstrip() + "…"


def _value(status: Status, partial_value: float | None, cfg: ScoringConfig, u: float) -> float:
    if status == Status.match:
        return 1.0
    if status == Status.partial:
        return partial_value if partial_value is not None else cfg.partial_default
    if status == Status.mismatch:
        return 0.0
    return u


@dataclass(frozen=True)
class _Row:
    req: Requirement
    status: Status
    partial_value: float | None
    weight: float


def _weight(req: Requirement, cfg: ScoringConfig) -> float:
    if req.kind == ReqKind.soft:
        return cfg.w_soft  # D55: личное качество весит одинаково, обязательное оно или нет
    return cfg.w_must if req.modality == Modality.must else cfg.w_nice


def _rows(reqs: list[Requirement], verdicts: list[Verdict], cfg: ScoringConfig) -> list[_Row]:
    by_req = {v.requirement_id: v for v in verdicts}
    out = []
    for req in reqs:
        v = by_req.get(req.id)
        out.append(
            _Row(
                req=req,
                status=v.status if v else Status.not_stated,  # нет вердикта — нет сведений
                partial_value=v.partial_value if v else None,
                weight=_weight(req, cfg),
            )
        )
    return out


def _total(rows: list[_Row], cfg: ScoringConfig, u: float) -> float:
    w_sum = sum(r.weight for r in rows)
    if not w_sum:
        return 0.0
    return round(
        100 * sum(r.weight * _value(r.status, r.partial_value, cfg, u) for r in rows) / w_sum, 1
    )


def _count(rows: list[_Row], modality: Modality) -> StatusCounts:
    counts = StatusCounts()
    for r in rows:
        if r.req.modality == modality:
            counts.total += 1
            setattr(counts, r.status.value, getattr(counts, r.status.value) + 1)
    return counts


def score_vacancy(
    vacancy: Document,
    reqs: list[Requirement],
    verdicts: list[Verdict],
    cfg: ScoringConfig | None = None,
) -> VacancyScore:
    cfg = cfg or load_scoring_config()
    rows = _rows(reqs, verdicts, cfg)
    score = _total(rows, cfg, cfg.unknown_value)
    score_min, score_max = _total(rows, cfg, 0.0), _total(rows, cfg, 1.0)
    must, nice = _count(rows, Modality.must), _count(rows, Modality.nice)
    # D55: личные качества не блокируют метку и не входят в долю подтверждённых
    hard = [r for r in rows if r.req.kind != ReqKind.soft]
    soft = len(rows) - len(hard)
    blocking = [
        r.req.id for r in hard if r.req.modality == Modality.must and r.status == Status.mismatch
    ]
    unknown = must.not_stated + nice.not_stated
    all_unknown = bool(rows) and unknown == len(rows)
    # D41: «с оговорками» — только если данных достаточно: подтверждена доля обязательных
    # (без обязательных — всех) или даже при худшем раскладе неуказанного балл не ниже порога
    hard_must, hard_nice = _count(hard, Modality.must), _count(hard, Modality.nice)
    base = hard_must if hard_must.total else hard_nice if hard_nice.total else nice
    confirmed = base.match + base.partial
    enough_data = bool(base.total) and confirmed >= cfg.caveats_min_confirmed * base.total
    low_data = not enough_data and score_min < cfg.caveats_min_score

    if (
        score >= cfg.fits_min_score
        and len(blocking) <= cfg.fits_max_blocking_gaps
        and not all_unknown
    ):
        label = FitLabel.fits
    elif score >= cfg.caveats_min_score and not low_data:
        label = FitLabel.fits_with_caveats
    else:
        label = FitLabel.not_fit

    # Вклад и потеря каждого требования при u = 0.5
    gain = {
        r.req.id: r.weight * _value(r.status, r.partial_value, cfg, cfg.unknown_value) for r in rows
    }
    loss = {r.req.id: r.weight - gain[r.req.id] for r in rows}
    order = {r.req.id: i for i, r in enumerate(rows)}
    top_plus = [k for k in sorted(gain, key=lambda k: (-gain[k], order[k])) if gain[k] > 0][:TOP_N]
    top_minus = [k for k in sorted(loss, key=lambda k: (-loss[k], order[k])) if loss[k] > 0][:TOP_N]

    texts = {r.req.id: _short(r.req.text) for r in rows}
    parts: list[str] = []
    if not rows:
        parts.append("В вакансии нет требований — балл не считается.")
    elif not must.total:
        parts.append("В вакансии нет обязательных требований: балл посчитан по желательным.")
    if rows:
        parts.append(
            f"Закрыто {must.match} из {must.total} обязательных и {nice.match} из {nice.total} "
            "желательных требований"
            + (f", частично — {must.partial + nice.partial}" if must.partial + nice.partial else "")
            + "."
        )
    if all_unknown:
        parts.append("По всем требованиям в резюме нет сведений: мало данных для вывода.")
    if unknown:
        parts.append(
            f"Не указано {unknown} {plural(unknown, _REQ)}, поэтому балл от {score_min:g} "
            f"до {score_max:g}."
        )
    if soft:
        parts.append(
            f"Личных качеств {soft}: весят как желательные требования и не влияют на метку, "
            "их стоит уточнить на собеседовании."
        )
    if label == FitLabel.not_fit and score >= cfg.caveats_min_score and low_data:
        which = "обязательных" if hard_must.total else "требований"
        parts.append(
            f"Мало данных: в резюме подтверждено {confirmed} из {base.total} {which}, "
            "поэтому «не подходит» до уточнения у кандидата — ответы могут поднять балл "
            f"до {score_max:g}."
        )
    plus = [k for k in top_plus if gain[k] >= 1]
    if plus:
        parts.append("Сильнее всего добавили: " + "; ".join(f"«{texts[k]}»" for k in plus) + ".")
    if top_minus:
        parts.append(
            "Больше всего потеряно на: " + "; ".join(f"«{texts[k]}»" for k in top_minus) + "."
        )
    if blocking:
        parts.append(
            "Обязательные требования без соответствия: "
            + "; ".join(f"«{texts[k]}»" for k in blocking)
            + ". Поэтому метка не может быть «подходит» (решает рекрутер)."
        )

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


def sort_key(s: VacancyScore) -> tuple[float, float, int, str]:
    """Балл ↓, доля закрытых обязательных ↓, меньше «не указано», затем id — без случайности."""
    return (-s.score, -_must_share(s), s.must.not_stated + s.nice.not_stated, s.vacancy_id)


def is_close(upper: VacancyScore, lower: VacancyScore, cfg: ScoringConfig) -> bool:
    return upper.score - lower.score < cfg.close_margin


def _comparison(upper: VacancyScore, lower: VacancyScore, cfg: ScoringConfig) -> str:
    diff = round(upper.score - lower.score)
    head = (
        f"{upper.vacancy_id} выше {lower.vacancy_id} на {diff} "
        f"{plural(diff, ('пункт', 'пункта', 'пунктов'))}"
        if diff
        else f"{upper.vacancy_id} выше {lower.vacancy_id} при равном балле"
    )
    reasons = []
    open_must = lower.must.total - lower.must.match
    if open_must > upper.must.total - upper.must.match:
        reasons.append(
            f"в {lower.vacancy_id} не подтверждены {open_must} из {lower.must.total} обязательных "
            "требований"
        )
    if lower.blocking_gaps and not upper.blocking_gaps:
        reasons.append(f"в {lower.vacancy_id} есть обязательные требования без соответствия")
    lower_unknown = lower.must.not_stated + lower.nice.not_stated
    upper_unknown = upper.must.not_stated + upper.nice.not_stated
    if lower_unknown > upper_unknown:
        reasons.append(
            f"в {lower.vacancy_id} больше неуказанного ({lower_unknown} против {upper_unknown})"
        )
    if not reasons:
        reasons.append(
            f"обязательных закрыто {upper.must.match} из {upper.must.total} против "
            f"{lower.must.match} из {lower.must.total}"
        )
    text = f"{head}: " + "; ".join(reasons) + "."
    if is_close(upper, lower, cfg):
        text += (
            f" Баллы почти равны (разница меньше {cfg.close_margin:g}): при других весах порядок "
            "может поменяться — сравните таблицы требований."
        )
    return text


def formula_text(cfg: ScoringConfig) -> str:
    return (
        "Балл = 100 · Σ(вес · значение) / Σ(вес). Вес: обязательное требование "
        f"{cfg.w_must:g}, желательное и обязанность {cfg.w_nice:g}, личное качество "
        f"{cfg.w_soft:g} (даже обязательное). Значение: «Соответствует» 1, "
        f"«Частично» {cfg.partial_default:g} (или доля порога, например 1,5 года из 3 = 0,5), "
        f"«Не соответствует» 0, «Не указано» {cfg.unknown_value:g}. Интервал — тот же расчёт, "
        "если все «Не указано» окажутся 0 или 1. Метка «подходит»: балл не ниже "
        f"{cfg.fits_min_score:g} и нет обязательных требований без соответствия (личные качества "
        "на метку не влияют); "
        f"«подходит с оговорками»: не ниже {cfg.caveats_min_score:g} и в резюме подтверждено "
        f"не меньше {cfg.caveats_min_confirmed:.0%} обязательных (или нижняя граница интервала "
        f"не ниже {cfg.caveats_min_score:g}); иначе «не подходит», мало данных. Веса одинаковы "
        "для всех вакансий и лежат в config/scoring.yaml."
    )


def rank(scores: list[VacancyScore], cfg: ScoringConfig | None = None) -> Ranking:
    cfg = cfg or load_scoring_config()
    items = sorted(scores, key=sort_key)
    return Ranking(
        items=items,
        best_vacancy_id=items[0].vacancy_id if items else None,
        comparison=[_comparison(a, b, cfg) for a, b in itertools.pairwise(items)],
        formula=formula_text(cfg),
    )
