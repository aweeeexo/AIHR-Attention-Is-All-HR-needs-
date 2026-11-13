"""Пакет: несколько резюме против одного набора вакансий (D38).

Каждое резюме — обычный прогон `pipeline.run` со своим отчётом и журналом исходящих: обезличивание,
балл и отчёт те же, что для одного кандидата. Вакансии маскируются первыми, поэтому их промпт
извлечения одинаков в каждом прогоне и LLM разбирает вакансию один раз (кэш, T03).

Пакет собирает из прогонов матрицу «кандидат × вакансия», порядок кандидатов на каждую вакансию
(та же формула и тот же tie-break, что у рейтинга вакансий, D11) и короткие выводы.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime

from aihr.config import Settings, get_settings
from aihr.contracts import (
    BatchCell,
    BatchResult,
    BatchResume,
    BatchVacancy,
    FitLabel,
    MatchResult,
    VacancyScore,
)
from aihr.llm import LLMClient
from aihr.pipeline import Progress, run
from aihr.score import is_close, load_scoring_config, sort_key
from aihr.score.summary import LABEL_RU

log = logging.getLogger(__name__)


def new_batch_id() -> str:
    return f"b{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


def _vacancy_summary(
    vid: str, ranked: list[tuple[str, VacancyScore]], names: dict[str, str]
) -> str:
    if not ranked:
        return "Ни один кандидат не обработан."
    good = [(rid, s) for rid, s in ranked if s.label != FitLabel.not_fit]
    if not good:
        rid, s = ranked[0]
        return (
            f"Прямо не подходит ни один кандидат. Ближе всех {names[rid]} ({rid}): балл "
            f"{s.score:g}, закрыто {s.must.match} из {s.must.total} обязательных — смотрите отчёт "
            "кандидата."
        )
    rid, best = good[0]
    text = (
        f"Лучший кандидат — {names[rid]} ({rid}): {LABEL_RU[best.label]}, балл {best.score:g}, "
        f"закрыто {best.must.match} из {best.must.total} обязательных."
    )
    if len(good) > 1:
        rid2, second = good[1]
        if is_close(best, second, load_scoring_config()):
            text += (
                f" {names[rid2]} ({rid2}) почти вровень ({second.score:g}): выбор — по таблицам "
                "требований."
            )
        text += f" Подходят ещё: {len(good) - 1}."
    return text


def build_batch(
    batch_id: str,
    filenames: list[str],
    results: list[MatchResult | None],
) -> BatchResult:
    """Матрица и выводы из готовых прогонов (по одному на резюме, None — прогон упал)."""
    resumes: list[BatchResume] = []
    cells: list[BatchCell] = []
    vacancies: dict[str, BatchVacancy] = {}
    scores: dict[str, list[tuple[str, VacancyScore]]] = {}
    errors, warnings = [], []
    names: dict[str, str] = {}

    for i, (filename, result) in enumerate(zip(filenames, results, strict=True), 1):
        rid = f"C{i}"
        names[rid] = filename
        entry = BatchResume(resume_id=rid, filename=filename)
        if result is None:
            warnings.append(f"{filename}: прогон не выполнен (см. лог).")
            resumes.append(entry)
            continue
        entry.run_id, entry.mode = result.run_id, result.mode
        for vac in result.vacancies:
            vacancies.setdefault(
                vac.id, BatchVacancy(vacancy_id=vac.id, filename=vac.filename, title=vac.title)
            )
        for err in result.errors:
            if result.resume is None and err.filename == filename:
                entry.error = err  # не прочиталось само резюме
            elif err not in errors:
                errors.append(err)  # ошибка вакансии повторяется в каждом прогоне — берём раз
        for w in result.warnings:
            if w not in warnings:
                warnings.append(w)
        if result.ranking:
            entry.best_vacancy_id = result.ranking.best_vacancy_id
            for s in result.ranking.items:
                scores.setdefault(s.vacancy_id, []).append((rid, s))
                cells.append(
                    BatchCell(
                        resume_id=rid,
                        vacancy_id=s.vacancy_id,
                        score=s.score,
                        score_min=s.score_min,
                        score_max=s.score_max,
                        label=s.label,
                        must_match=s.must.match,
                        must_total=s.must.total,
                    )
                )
        resumes.append(entry)

    for vid, vac in vacancies.items():
        ranked = sorted(scores.get(vid, []), key=lambda x: (sort_key(x[1]), int(x[0][1:])))
        vac.candidates = [rid for rid, _ in ranked]
        vac.summary = _vacancy_summary(vid, ranked, names)

    ok = [r for r in resumes if r.run_id and r.error is None]
    fitting = {c.resume_id for c in cells if c.label != FitLabel.not_fit}
    summary = (
        f"Обработано резюме: {len(ok)} из {len(resumes)}, вакансий: {len(vacancies)}. "
        f"Хотя бы на одну вакансию подходят (с оговорками или без): {len(fitting)}."
    )
    return BatchResult(
        batch_id=batch_id,
        resumes=resumes,
        vacancies=sorted(vacancies.values(), key=lambda v: int(v.vacancy_id[1:])),
        cells=cells,
        errors=errors,
        warnings=warnings,
        summary=summary,
    )


def run_batch(
    resumes: list[tuple[bytes, str]],
    vacancies: list[tuple[bytes, str]],
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    save: bool = True,
    progress: Progress | None = None,
) -> BatchResult:
    settings = settings or get_settings()
    llm = llm or LLMClient(settings)
    batch_id = new_batch_id()
    results: list[MatchResult | None] = []
    n = len(resumes)
    for i, (data, name) in enumerate(resumes):

        def step(stage: str, fraction: float, i: int = i) -> None:
            if progress is not None:
                progress(f"Кандидат {i + 1} из {n}: {stage}", (i + fraction) / n)

        try:
            results.append(
                run((data, name), vacancies, settings=settings, llm=llm, save=save, progress=step)
            )
        except Exception:  # принцип 7: сбой одного кандидата не роняет пакет
            log.exception("пакет %s: сбой прогона резюме", batch_id)
            results.append(None)
    batch = build_batch(batch_id, [name for _, name in resumes], results)
    if save:
        path = settings.runs_dir / "batches" / f"{batch_id}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(batch.model_dump_json(indent=2), encoding="utf-8", newline="\n")
        except OSError as exc:
            log.warning("не удалось сохранить пакет: %s", exc)
            batch.warnings.append("Пакет не сохранён на диск (см. лог).")
    return batch
