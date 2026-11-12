"""Командная строка: `aihr match`, `aihr demo` и отладочные команды извлечения."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from aihr import extract, fallback, usecases
from aihr.config import get_settings, setup_logging
from aihr.contracts import DocKind, Document, IngestFailure, MatchResult
from aihr.ingest import load_document
from aihr.inputs import collect_vacancies, read_files
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
    """Инварианты результата + ожидаемое число вакансий в рейтинге и отсутствие ошибок."""
    expect = {"ranked": expected_vacancies, "no_errors": True}
    return usecases.invariants(result) + usecases.expectations(result, expect)


def _print_checks(checks: list[tuple[str, bool]]) -> bool:
    for name, ok in checks:
        typer.echo(f"  [{'ok' if ok else 'FAIL'}] {name}")
    return all(ok for _, ok in checks)


@app.command()
def demo(
    case: Annotated[
        str | None, typer.Option(help="Только этот use case из examples/ (имя папки)")
    ] = None,
    save: Annotated[
        bool, typer.Option("--save", help="Записать examples/<case>/result.md — пример результата")
    ] = False,
    examples: Annotated[Path, typer.Option(help="Папка с use cases")] = Path("examples"),
) -> None:
    """Прогон use cases из examples/ и проверка результата: схема, цитаты, ожидания."""
    root = Path.cwd()
    cases = usecases.load_cases(examples, root) if examples.is_dir() else []
    if case:
        cases = [c for c in cases if c.name == case]
    if not cases:
        typer.echo(f"В {examples} нет use cases (папки с case.json).", err=True)
        raise typer.Exit(2)
    all_ok = True
    for uc in cases:
        typer.echo(f"\n== {uc.name}: {uc.title}")
        result, checks = usecases.run_case(uc)
        typer.echo(summary(result))
        all_ok &= _print_checks(checks)
        if save:
            out = examples / uc.name / "result.md"
            out.write_text(usecases.summary_markdown(uc, result), encoding="utf-8", newline="\n")
            typer.echo(f"  записано: {out}")
    if not all_ok:
        typer.echo("demo: есть проваленные проверки")
        raise typer.Exit(1)
    typer.echo("demo: всё в порядке")


if __name__ == "__main__":
    app()
