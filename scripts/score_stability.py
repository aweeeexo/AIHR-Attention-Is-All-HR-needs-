"""Проверка устойчивости рейтинга к весам (T08): меняется ли порядок вакансий.

Берёт сохранённые результаты прогонов (data/runs/*/result.json или пути из аргументов),
пересчитывает балл и рейтинг с вариантами весов и печатает таблицу в Markdown.

    uv run python scripts/score_stability.py data/runs/*/result.json > eval/stability.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihr.contracts import MatchResult  # noqa: E402
from aihr.score import load_scoring_config, rank, score_vacancy  # noqa: E402

VARIANTS: list[tuple[str, dict[str, float]]] = [
    ("базовые веса", {}),
    ("must = 2", {"w_must": 2}),
    ("must = 4", {"w_must": 4}),
    ("частично = 0.4", {"partial_default": 0.4}),
    ("частично = 0.6", {"partial_default": 0.6}),
]


def order(result: MatchResult, changes: dict[str, float]) -> list[str]:
    cfg = load_scoring_config(ROOT / "config" / "scoring.yaml").with_changes(**changes)
    by_id = {v.id: v for v in result.vacancies}
    scores = [
        score_vacancy(by_id[vid], result.requirements[vid], result.verdicts[vid], cfg)
        for vid in result.verdicts
        if vid in by_id
    ]
    return [s.vacancy_id for s in rank(scores, cfg).items]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="*", type=Path)
    args = parser.parse_args(argv)
    paths = args.results or sorted((ROOT / "data" / "runs").glob("*/result.json"))
    if not paths:
        sys.stderr.write("нет result.json: сначала запустите прогоны\n")
        return 1

    header = "| Резюме | " + " | ".join(name for name, _ in VARIANTS) + " | Порядок устойчив |"
    lines = [header, "|" + "---|" * (len(VARIANTS) + 2)]
    stable_all = True
    for path in paths:
        result = MatchResult.model_validate_json(path.read_text(encoding="utf-8"))
        if not result.verdicts:
            continue
        orders = [order(result, changes) for _, changes in VARIANTS]
        stable = all(o == orders[0] for o in orders)
        stable_all &= stable
        name = result.resume.filename if result.resume else path.parent.name
        cells = " | ".join(" > ".join(o) for o in orders)
        lines.append(f"| {name} | {cells} | {'да' if stable else '**нет**'} |")
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.write(
        f"\nПорядок не меняется ни для одного резюме: {'да' if stable_all else 'нет'}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
