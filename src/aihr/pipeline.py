"""Оркестратор: загрузка → маскирование → извлечение → сопоставление → балл → рейтинг → отчёт.

Ошибка одного документа не роняет прогон (принцип 7): битый файл даёт IngestError в
MatchResult.errors, сбой на шаге вакансии — предупреждение, остальные вакансии считаются.
Если LLM недоступна, прогон переходит в режим без LLM с предупреждением.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
    LLMUnavailable,
    MatchResult,
    PrivacyViolation,
    Report,
    Requirement,
    VacancyScore,
    Verdict,
)
from aihr.ingest import load_document
from aihr.llm import LLMClient
from aihr.match import apply_rules, match_vacancy
from aihr.normalize import enrich_profile
from aihr.privacy import PrivacyContext, mask_document
from aihr.privacy.outbound import OutboundLog
from aihr.report import build_report
from aihr.retrieve import Retriever
from aihr.score import rank, score_vacancy

log = logging.getLogger(__name__)

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")

T = TypeVar("T")


def new_run_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


class _Timings:
    def __init__(self) -> None:
        self.ms: dict[str, int] = defaultdict(int)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] += int((time.perf_counter() - started) * 1000)


class _Run:
    """Состояние одного прогона: режим, предупреждения, переход на fallback."""

    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self.settings = settings
        self.llm = llm
        self.mode: Literal["llm", "fallback"] = "llm" if llm.available else "fallback"
        self.warnings: list[str] = []
        if settings.llm_provider == "openai_compatible" and not llm.available:
            self.warnings.append(
                "LLM не настроена (нет LLM_BASE_URL или LLM_MODEL): работаем в режиме без LLM."
            )

    def call(self, with_llm: Callable[[], T], without_llm: Callable[[], T]) -> T:
        if self.mode == "llm":
            try:
                return with_llm()
            except PrivacyViolation as exc:
                # Запрос не ушёл. Только этот шаг считаем без LLM, прогон продолжается с LLM
                self.warnings.append(f"Запрос к LLM заблокирован проверкой ПДн ({exc}).")
                log.warning("guard заблокировал запрос: %s", exc)
                return without_llm()
            except LLMUnavailable as exc:
                self.mode = "fallback"
                self.warnings.append(f"LLM недоступна ({exc}): дальше режим без LLM.")
                log.warning("LLM недоступна, переход в режим без LLM: %s", exc)
        return without_llm()


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
        if resume_doc is not None:
            resume_doc = mask_document(resume_doc, ctx)
        vac_docs = [mask_document(d, ctx) for d in vac_docs]

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

        # 4. Каждая вакансия отдельно: сбой одной не трогает остальные
        for vac in vac_docs:
            step = "extract_requirements"
            try:
                with t.step(step):
                    reqs = state.call(
                        lambda v=vac: extract.extract_requirements(v, llm),
                        lambda v=vac: fallback.extract_requirements_fallback(v),
                    )
                if not reqs:
                    errors.append(
                        IngestError(
                            code=IngestErrorCode.no_requirements,
                            filename=vac.filename,
                            message="Из вакансии не извлечено ни одного требования.",
                            hint="Проверьте, что в файле есть раздел с требованиями.",
                        )
                    )
                    continue
                step = "match"
                with t.step(step):
                    vs = state.call(
                        lambda r=reqs: match_vacancy(r, profile, resume_doc, retriever, llm),
                        lambda r=reqs: fallback.match_vacancy_fallback(
                            r, profile, resume_doc, retriever
                        ),
                    )
                    by_id = {r.id: r for r in reqs}
                    vs = [apply_rules(by_id[v.requirement_id], v, profile) for v in vs]
                step = "score"
                with t.step(step):
                    score = score_vacancy(vac, reqs, vs)
            except Exception as exc:
                log.exception("%s: сбой на шаге %s", vac.id, step)
                state.warnings.append(
                    f"{vac.filename}: не удалось обработать (шаг {step}, {type(exc).__name__})."
                )
                continue
            requirements[vac.id], verdicts[vac.id], scores[vac.id] = reqs, vs, score

    # 5. Рейтинг считает код (D11)
    with t.step("rank"):
        ranking = rank(list(scores.values())) if resume_doc is not None else None

    # 6. Отчёт
    with t.step("report"):
        for vac in vac_docs:
            if vac.id not in scores or profile is None or resume_doc is None:
                continue
            try:
                reports[vac.id] = build_report(
                    vac,
                    requirements[vac.id],
                    verdicts[vac.id],
                    scores[vac.id],
                    profile,
                    resume_doc,
                    llm,
                )
            except Exception as exc:
                log.exception("%s: сбой при сборке отчёта", vac.id)
                state.warnings.append(f"{vac.filename}: отчёт не собран ({type(exc).__name__}).")

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
        timings_ms=dict(t.ms),
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
