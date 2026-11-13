"""Use cases из examples/ (T12): вход, прогон, проверка ожидаемого результата.

Ожидания — свойства результата (лучшая вакансия, доля «Не указано», ширина интервала, коды
ошибок), а не точные числа: они должны выполняться и с LLM, и без неё.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aihr.contracts import MatchResult, Status
from aihr.pipeline import run


@dataclass
class UseCase:
    name: str
    title: str
    description: str
    resume: Path
    vacancies: list[Path]
    expect: dict[str, Any]


def load_cases(examples_dir: Path, root: Path) -> list[UseCase]:
    cases = []
    for path in sorted(examples_dir.glob("*/case.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        cases.append(
            UseCase(
                name=path.parent.name,
                title=raw["title"],
                description=raw["description"],
                resume=root / raw["resume"],
                vacancies=[root / v for v in raw["vacancies"]],
                expect=raw.get("expect", {}),
            )
        )
    return cases


def invariants(result: MatchResult) -> list[tuple[str, bool]]:
    """Свойства, которые обязан соблюдать любой результат (принципы 1, 2)."""
    checks: list[tuple[str, bool]] = []
    restored = MatchResult.model_validate_json(result.model_dump_json())
    checks.append(("MatchResult проходит схему туда и обратно", restored == result))
    checks.append(("резюме загружено", result.resume is not None))
    frag_text = {f.id: f.text for f in result.resume.fragments} if result.resume else {}
    quotes_ok = stated_ok = True
    for verdicts in result.verdicts.values():
        for v in verdicts:
            if v.status != Status.not_stated and not v.evidence:
                stated_ok = False
            for ev in v.evidence:
                quotes_ok &= frag_text.get(ev.fragment_id) == ev.quote
    checks.append(("каждая цитата совпадает с фрагментом резюме", quotes_ok))
    checks.append(("вывод без фрагмента только «Не указано»", stated_ok))
    checks.append(
        ("отчёт для каждой вакансии в рейтинге", set(result.reports) == set(result.verdicts))
    )
    return checks


def expectations(result: MatchResult, expect: dict[str, Any]) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    items = result.ranking.items if result.ranking else []
    files = {v.id: v.filename for v in result.vacancies}
    if "ranked" in expect:
        checks.append((f"в рейтинге {expect['ranked']} вакансии", len(items) == expect["ranked"]))
    if expect.get("no_errors"):
        checks.append(("нет ошибок загрузки", not result.errors))
    if "best_vacancy_file" in expect:
        best = files.get(result.ranking.best_vacancy_id or "") if result.ranking else None
        checks.append((f"первая в рейтинге — {expect['best_vacancy_file']}",
                       best == expect["best_vacancy_file"]))  # fmt: skip
    if expect.get("best_has_most_must_matched") and items:
        top = items[0].must.match
        checks.append(("у первой больше всех закрытых обязательных",
                       all(top >= s.must.match for s in items)))  # fmt: skip
    if "min_not_stated_share" in expect:
        all_v = [v for vs in result.verdicts.values() for v in vs]
        share = sum(v.status == Status.not_stated for v in all_v) / len(all_v) if all_v else 0
        checks.append((f"«Не указано» не меньше {expect['min_not_stated_share']:.0%} ({share:.0%})",
                       share >= expect["min_not_stated_share"]))  # fmt: skip
    if "min_interval_width" in expect:
        width = min((s.score_max - s.score_min for s in items), default=0)
        checks.append((f"интервал балла не уже {expect['min_interval_width']} ({width:g})",
                       width >= expect["min_interval_width"]))  # fmt: skip
    if expect.get("questions"):
        checks.append(("есть вопросы кандидату", any(r.questions for r in result.reports.values())))
    if "warning_contains" in expect:
        warnings = list(result.warnings) + (result.resume.warnings if result.resume else [])
        needle = expect["warning_contains"]
        checks.append((f"предупреждение «{needle}»", any(needle in w for w in warnings)))
    for err in expect.get("errors", []):
        found = any(e.filename == err["filename"] and e.code.value == err["code"]
                    for e in result.errors)  # fmt: skip
        checks.append((f"{err['filename']}: {err['code']}", found))
    return checks


def run_case(case: UseCase) -> tuple[MatchResult, list[tuple[str, bool]]]:
    resume = (case.resume.read_bytes(), case.resume.name)
    vacancies = [(p.read_bytes(), p.name) for p in case.vacancies]
    result = run(resume, vacancies)
    return result, invariants(result) + expectations(result, case.expect)


def summary_markdown(case: UseCase, result: MatchResult) -> str:
    """Пример результата для README: рейтинг и начало таблицы требований лучшей вакансии."""
    lines = [f"# {case.title}", "", case.description, "", f"Режим прогона: `{result.mode}`.", ""]
    files = {v.id: v.filename for v in result.vacancies}
    if result.errors:
        lines += ["**Ошибки загрузки:**", ""]
        lines += [
            f"- `{e.filename}` — `{e.code.value}`: {e.message} {e.hint}" for e in result.errors
        ]
        lines.append("")
    if result.ranking and result.ranking.items:
        lines += ["| Место | Вакансия | Балл | Интервал | Метка |", "|---|---|---|---|---|"]
        for i, s in enumerate(result.ranking.items, 1):
            lines.append(f"| {i} | {files[s.vacancy_id]} | {s.score:g} | {s.score_min:g}–"
                         f"{s.score_max:g} | {s.label.value} |")  # fmt: skip
        best = result.ranking.items[0]
        lines += [
            "",
            f"**Почему {files[best.vacancy_id]} на первом месте:** {best.explanation}",
            "",
        ]
        report = result.reports.get(best.vacancy_id)
        if report:
            lines += ["| Требование | Тип | Статус | Подтверждение в резюме |", "|---|---|---|---|"]
            for row in report.rows[:8]:
                quote = " … ".join(e.quote for e in row.resume_evidence)[:120] or "—"
                req = row.requirement[:90].replace("|", "/")
                lines.append(f"| {req} | {row.modality.value} | {row.status_ru} | "
                             f"{quote.replace('|', '/')} |")  # fmt: skip
            if report.questions:
                lines += ["", "**Вопросы кандидату (первые 3):**", ""]
                lines += [f"- {q.text}" for q in report.questions[:3]]
    return "\n".join(lines) + "\n"
