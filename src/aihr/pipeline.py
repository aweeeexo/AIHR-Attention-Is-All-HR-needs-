"""Оркестратор: загрузка → маскирование → извлечение → сопоставление → балл → рейтинг → отчёт.

Ошибка одного документа не роняет прогон (принцип 7): битый файл даёт IngestError в
MatchResult.errors, сбой на шаге вакансии — предупреждение, остальные вакансии считаются.
Если LLM недоступна, прогон переходит в режим без LLM с предупреждением.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, TypeVar

from aihr import extract, fallback
from aihr.config import Settings, get_settings
from aihr.contracts import (
    CandidateProfile,
    DocKind,
    Document,
    IngestError,
    IngestErrorCode,
    IngestFailure,
    LLMBadOutput,
    LLMUnavailable,
    MatchResult,
    PrivacyViolation,
    Report,
    Requirement,
    VacancyScore,
    Verdict,
)
from aihr.ingest import load_document, make_error
from aihr.llm import LLMClient
from aihr.match import apply_rules, attach_quotes, match_vacancy
from aihr.normalize import enrich_profile
from aihr.privacy import PrivacyContext, mask_document
from aihr.privacy.outbound import OutboundLog
from aihr.report import build_report
from aihr.retrieve import Retriever
from aihr.score import rank, score_vacancy
from aihr.score.summary import ranking_summary

log = logging.getLogger(__name__)

MAX_LLM_FAILURES = 2  # сколько сбоев LLM терпим, прежде чем весь прогон пойдёт без неё

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")

T = TypeVar("T")


def new_run_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


class _Timings:
    """Время шагов. Шаги вакансий идут параллельно, поэтому это сумма по вакансиям."""

    def __init__(self) -> None:
        self.ms: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            with self._lock:
                self.ms[name] += int((time.perf_counter() - started) * 1000)


class _Run:
    """Состояние одного прогона: режим, предупреждения, переход на fallback."""

    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self.settings = settings
        self.llm = llm
        self.mode: Literal["llm", "fallback"] = "llm" if llm.available else "fallback"
        self.warnings: list[str] = []
        self.llm_failures = 0
        self._lock = threading.Lock()
        if settings.llm_provider == "none":
            self.warnings.append(
                "Режим без LLM (LLM_PROVIDER=none): требования и сопоставление — по правилам и "
                "совпадению терминов, результат упрощённый."
            )
        elif not llm.available:
            self.warnings.append(
                "LLM не настроена (нет LLM_BASE_URL или LLM_MODEL): работаем в режиме без LLM."
            )

    def warn(self, text: str) -> None:
        with self._lock:
            if text not in self.warnings:
                self.warnings.append(text)

    def call(self, with_llm: Callable[[], T], without_llm: Callable[[], T]) -> T:
        if self.mode == "llm":
            try:
                return with_llm()
            except PrivacyViolation as exc:
                # Запрос не ушёл. Только этот шаг считаем без LLM, прогон продолжается с LLM
                self.warn(f"Запрос к LLM заблокирован проверкой ПДн ({exc}).")
                log.warning("guard заблокировал запрос: %s", exc)
                return without_llm()
            except LLMBadOutput as exc:
                # Модель ответила не по схеме и после повторов: этот шаг без LLM, прогон — с LLM
                self.warn(f"Ответ LLM не прошёл проверку схемы ({exc}); шаг посчитан без LLM.")
                log.warning("невалидный ответ LLM: %s", exc)
                return without_llm()
            except LLMUnavailable as exc:
                # Первый сбой — только этот шаг без LLM (у провайдеров бывают единичные таймауты),
                # второй — дальше весь прогон без LLM, чтобы не ждать таймаут на каждом шаге
                with self._lock:
                    self.llm_failures += 1
                    switched = self.mode == "llm" and self.llm_failures >= MAX_LLM_FAILURES
                    if switched:
                        self.mode = "fallback"
                if switched:
                    self.warn(f"LLM недоступна ({exc}): дальше режим без LLM.")
                    log.warning("LLM недоступна, переход в режим без LLM: %s", exc)
                else:
                    self.warn(f"LLM не ответила на одном шаге ({exc}): этот шаг посчитан без LLM.")
                    log.warning("LLM не ответила, шаг без LLM: %s", exc)
        return without_llm()


@dataclass
class _VacancyOutcome:
    reqs: list[Requirement] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    score: VacancyScore | None = None
    error: IngestError | None = None
    warning: str | None = None


def _map[T](fn: Callable[[Document], T], docs: list[Document], settings: Settings) -> list[T]:
    """Параллельно по вакансиям, не больше LLM_CONCURRENCY потоков. Порядок — как у docs."""
    workers = min(len(docs), settings.llm_concurrency)
    if workers <= 1:
        return [fn(d) for d in docs]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vacancy") as pool:
        return list(pool.map(fn, docs))


def _load(
    data: bytes, filename: str, kind: DocKind, doc_id: str, errors: list[IngestError]
) -> Document | None:
    try:
        return load_document(data, filename, kind, doc_id)
    except IngestFailure as exc:
        errors.append(exc.error)
    except Exception:
        log.exception("%s: непредвиденная ошибка загрузки", doc_id)
        errors.append(
            IngestError(
                code=IngestErrorCode.corrupted,
                filename=filename,
                message="Не удалось прочитать файл.",
                hint="Пересохраните документ в docx или pdf.",
            )
        )
    return None


def run(
    resume: tuple[bytes, str],
    vacancies: list[tuple[bytes, str]],
    *,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    save: bool = True,
) -> MatchResult:
    settings = settings or get_settings()
    llm = llm or LLMClient(settings)
    t = _Timings()
    run_id = new_run_id()
    ctx = PrivacyContext()  # таблица замен ПДн — только в памяти этого прогона
    outbound_path = settings.runs_dir / run_id / "outbound.jsonl"
    llm = llm.for_run(ctx, OutboundLog(outbound_path) if save else None)
    state = _Run(settings, llm)
    errors: list[IngestError] = []
    started = time.perf_counter()

    # 1. Загрузка — локально, без LLM
    with t.step("ingest"):
        resume_doc = _load(resume[0], resume[1], DocKind.resume, "R", errors)
        vac_docs = [
            doc
            for i, (data, name) in enumerate(vacancies, 1)
            if (doc := _load(data, name, DocKind.vacancy, f"V{i}", errors)) is not None
        ]

    # 2. Маскирование: наружу уходит только masked_text
    with t.step("mask"):
        # Вакансии — первыми: номера их токенов не зависят от резюме, текст промпта извлечения
        # одинаков для любого кандидата, и вакансия разбирается один раз (кэш, T04 шаг 9)
        vac_docs = [mask_document(d, ctx) for d in vac_docs]
        if resume_doc is not None:
            resume_doc = mask_document(resume_doc, ctx)

    profile: CandidateProfile | None = None
    requirements: dict[str, list[Requirement]] = {}
    verdicts: dict[str, list[Verdict]] = {}
    scores: dict[str, VacancyScore] = {}
    reports: dict[str, Report] = {}

    if resume_doc is not None:
        # 3. Профиль кандидата
        with t.step("extract_profile"):
            doc = resume_doc
            profile = state.call(
                lambda: extract.extract_profile(doc, llm),
                lambda: fallback.extract_profile_fallback(doc),
            )
            profile = enrich_profile(profile, settings.today_ym())
        retriever = Retriever(resume_doc)

        # 4. Каждая вакансия отдельно и параллельно: сбой одной не трогает остальные
        def process(vac: Document) -> _VacancyOutcome:
            out = _VacancyOutcome()
            step = "extract_requirements"
            try:
                with t.step(step):
                    reqs = state.call(
                        lambda: extract.extract_requirements(vac, llm),
                        lambda: fallback.extract_requirements_fallback(vac),
                    )
                if not reqs:
                    out.error = make_error(IngestErrorCode.no_requirements, vac.filename)
                    return out
                step = "match"
                with t.step(step):
                    vs = state.call(
                        lambda: match_vacancy(reqs, profile, resume_doc, retriever, llm),
                        lambda: fallback.match_vacancy_fallback(
                            reqs, profile, resume_doc, retriever
                        ),
                    )
                    by_id = {r.id: r for r in reqs}
                    # Правила (стаж, уровни) могут добавить фрагменты — цитаты снова ставит код
                    vs = [
                        attach_quotes(apply_rules(by_id[v.requirement_id], v, profile), resume_doc)
                        for v in vs
                    ]
                step = "score"
                with t.step(step):
                    out.score = score_vacancy(vac, reqs, vs)
                out.reqs, out.verdicts = reqs, vs
            except Exception as exc:
                log.exception("%s: сбой на шаге %s", vac.id, step)
                out.warning = (
                    f"{vac.filename}: не удалось обработать (шаг {step}, {type(exc).__name__})."
                )
            return out

        for vac, out in zip(vac_docs, _map(process, vac_docs, settings), strict=True):
            if out.error:
                errors.append(out.error)
            if out.warning:
                state.warn(out.warning)
            if out.score is not None:
                requirements[vac.id] = out.reqs
                verdicts[vac.id] = out.verdicts
                scores[vac.id] = out.score

    # 5. Рейтинг считает код (D11)
    with t.step("rank"):
        ranking = rank(list(scores.values())) if resume_doc is not None else None
        if ranking is not None:  # итог: лучшая вакансия или «прямо не подходит ни одна» (D35)
            ranking = ranking.model_copy(
                update={"summary": ranking_summary(ranking, requirements, verdicts)}
            )

    # 6. Отчёт
    def report(vac: Document) -> Report | str:
        try:
            return build_report(
                vac,
                requirements[vac.id],
                verdicts[vac.id],
                scores[vac.id],
                profile,  # type: ignore[arg-type]
                resume_doc,  # type: ignore[arg-type]
                llm if state.mode == "llm" else None,
                ranking=ranking,
            )
        except Exception as exc:
            log.exception("%s: сбой при сборке отчёта", vac.id)
            return f"{vac.filename}: отчёт не собран ({type(exc).__name__})."

    with t.step("report"):
        ready = [v for v in vac_docs if v.id in scores and profile is not None and resume_doc]
        for vac, rep_ in zip(ready, _map(report, ready, settings), strict=True):
            if isinstance(rep_, str):
                state.warn(rep_)
            else:
                reports[vac.id] = rep_

    t.ms["total"] = int((time.perf_counter() - started) * 1000)
    result = MatchResult(
        run_id=run_id,
        mode=state.mode,
        resume=resume_doc,
        profile=profile,
        vacancies=vac_docs,
        requirements=requirements,
        verdicts=verdicts,
        ranking=ranking,
        reports=reports,
        errors=errors,
        warnings=state.warnings,
        timings_ms={**t.ms, **llm.stats.as_timings()},
        outbound_log_path=str(outbound_path) if save and outbound_path.is_file() else None,
    )
    if save:
        _save(result, settings)
    return result


def _save(result: MatchResult, settings: Settings) -> None:
    run_dir = settings.runs_dir / result.run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8", newline="\n"
        )
    except OSError as exc:
        log.warning("не удалось сохранить результат прогона: %s", exc)
        result.warnings.append("Результат не сохранён на диск (см. лог).")
