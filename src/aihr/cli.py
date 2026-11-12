"""Командная строка: `aihr match`, `aihr demo` и отладочные команды извлечения."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from aihr import extract, fallback
from aihr.config import get_settings, setup_logging
from aihr.contracts import DocKind, Document, IngestFailure, MatchResult, Status
from aihr.ingest import load_document
from aihr.inputs import case_files, collect_vacancies, read_files
from aihr.llm import LLMClient
from aihr.pipeline import run
from aihr.privacy import PrivacyContext, mask_document
from aihr.report import LABEL_RU

app = typer.Typer(
    help="AIHR: сопоставление резюме с вакансиями.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Подробный лог")] = False,
) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # консоль Windows и перенаправление в файл
    setup_logging("DEBUG" if verbose else None)


def summary(result: MatchResult) -> str:
    lines = [f"Прогон {result.run_id}, режим: {result.mode}"]
    if result.ranking and result.ranking.items:
        lines.append("Рейтинг вакансий:")
        for i, s in enumerate(result.ranking.items, 1):
            title = (s.title or "")[:70]
            lines.append(
                f"  {i}. {s.vacancy_id} «{title}» — {s.score:g} "
                f"(от {s.score_min:g} до {s.score_max:g}), {LABEL_RU[s.label]}"
            )
    for err in result.errors:
        lines.append(f"Ошибка: {err.filename}: {err.message} {err.hint}")
    for warning in result.warnings:
        lines.append(f"Предупреждение: {warning}")
    lines.append(f"Результат: {get_settings().runs_dir / result.run_id / 'result.json'}")
    return "\n".join(lines)


@app.command()
def match(
    resume: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Файл резюме: docx, pdf, txt")
    ],
    vacancies: Annotated[
        list[Path],
        typer.Option(exists=True, help="Файл вакансии или папка; можно повторять"),
    ],
    out: Annotated[Path | None, typer.Option(help="Куда записать MatchResult в JSON")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Напечатать весь JSON")] = False,
) -> None:
    """Сопоставить одно резюме с набором вакансий."""
    vacancy_paths = collect_vacancies(vacancies, exclude=resume)
    if not vacancy_paths:
        typer.echo("Не найдено ни одной вакансии (docx, pdf, txt).", err=True)
        raise typer.Exit(2)
    result = run(read_files([resume])[0], read_files(vacancy_paths))
    payload = result.model_dump_json(indent=2)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8", newline="\n")
    typer.echo(payload if as_json else summary(result))


def _load_masked(path: Path, kind: DocKind, doc_id: str) -> Document:
    try:
        doc = load_document(path.read_bytes(), path.name, kind, doc_id)
    except IngestFailure as exc:
        typer.echo(f"{exc.error.code.value}: {exc.error.message} {exc.error.hint}", err=True)
        raise typer.Exit(1) from exc
    return mask_document(doc, PrivacyContext())


@app.command("extract-requirements")
def extract_requirements_cmd(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Файл вакансии")],
) -> None:
    """Отладка: требования вакансии в JSON."""
    doc = _load_masked(file, DocKind.vacancy, "V1")
    llm = LLMClient()
    reqs = (
        extract.extract_requirements(doc, llm)
        if llm.available
        else fallback.extract_requirements_fallback(doc)
    )
    typer.echo(json.dumps([r.model_dump(mode="json") for r in reqs], ensure_ascii=False, indent=2))


@app.command("extract-profile")
def extract_profile_cmd(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Файл резюме")],
) -> None:
    """Отладка: профиль кандидата в JSON."""
    doc = _load_masked(file, DocKind.resume, "R")
    llm = LLMClient()
    profile = (
        extract.extract_profile(doc, llm)
        if llm.available
        else fallback.extract_profile_fallback(doc)
    )
    typer.echo(profile.model_dump_json(indent=2))


def check_result(result: MatchResult, expected_vacancies: int) -> list[tuple[str, bool]]:
    """Инварианты, которые обязан соблюдать любой результат."""
    checks: list[tuple[str, bool]] = []
    restored = MatchResult.model_validate_json(result.model_dump_json())
    checks.append(("MatchResult проходит схему туда и обратно", restored == result))
    checks.append(("резюме загружено", result.resume is not None))
    ranked = len(result.ranking.items) if result.ranking else 0
    checks.append((f"в рейтинге {expected_vacancies} вакансий", ranked == expected_vacancies))
    checks.append(("нет ошибок загрузки", not result.errors))

    frag_text = {f.id: f.text for f in result.resume.fragments} if result.resume else {}
    quotes_ok = True
    stated_have_evidence = True
    for verdicts in result.verdicts.values():
        for v in verdicts:
            if v.status != Status.not_stated and not v.evidence:
                stated_have_evidence = False
            for ev in v.evidence:
                quotes_ok &= frag_text.get(ev.fragment_id) == ev.quote
    checks.append(("каждая цитата совпадает с фрагментом резюме", quotes_ok))
    checks.append(("вывод без фрагмента только «Не указано»", stated_have_evidence))
    checks.append(
        ("отчёт для каждой вакансии в рейтинге", set(result.reports) == set(result.verdicts))
    )
    return checks


@app.command()
def demo(
    resume: Annotated[
        str | None, typer.Option(help="Часть имени резюме из примера; по умолчанию первое")
    ] = None,
) -> None:
    """Прогон примера из кейса и проверка результата по схеме."""
    settings = get_settings()
    resumes, vacancies = case_files(settings.case_dir)
    if resume:
        resumes = [p for p in resumes if resume.lower() in p.name.lower()]
    if not resumes or not vacancies:
        typer.echo(f"В {settings.case_dir} нет резюме или вакансий примера.", err=True)
        raise typer.Exit(2)
    result = run(read_files(resumes[:1])[0], read_files(vacancies))
    typer.echo(summary(result))
    checks = check_result(result, len(vacancies))
    for name, ok in checks:
        typer.echo(f"  [{'ok' if ok else 'FAIL'}] {name}")
    if not all(ok for _, ok in checks):
        raise typer.Exit(1)
    typer.echo("demo: всё в порядке")


if __name__ == "__main__":
    app()
