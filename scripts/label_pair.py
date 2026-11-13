"""Помощник второй разметки эталона (T10): требования вакансии и фрагменты резюме одной пары.

    uv run python scripts/label_pair.py R2 V1            # показать требования и резюме
    uv run python scripts/label_pair.py R2 V1 --template # создать шаблон для разметки

Шаблон ложится в eval/golden/second/verdicts_R2_V1.json: у каждого требования пустые status,
fragment_ids и evidence_type — их заполняет разметчик. Готовую первую разметку
(eval/golden/verdicts_*.json) скрипт не показывает: вторая разметка должна быть независимой.

Резюме: R1 — Иванов, R2 — Петров, R3 — Семенов, R4 — Петрова (как в eval/golden).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihr.contracts import DocKind  # noqa: E402
from aihr.ingest import load_document  # noqa: E402
from aihr.inputs import case_files  # noqa: E402

CASE = ROOT / "data" / "case"
RESUMES = {"R1": "Иванов", "R2": "Петров", "R3": "Семенов", "R4": "Петрова"}
SECOND = ROOT / "eval" / "golden" / "second"


def _resume_path(rid: str) -> Path:
    resumes, _ = case_files(CASE)
    return next(p for p in resumes if p.name.split("_")[0].strip().split()[0] == RESUMES[rid])


def _vacancy_path(vid: str) -> Path:
    _, vacancies = case_files(CASE)
    return vacancies[int(vid[1:]) - 1]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("resume", choices=sorted(RESUMES))
    ap.add_argument("vacancy", choices=["V1", "V2", "V3"])
    ap.add_argument("--template", action="store_true", help="создать шаблон разметки")
    args = ap.parse_args()

    rpath, vpath = _resume_path(args.resume), _vacancy_path(args.vacancy)
    reqs = json.loads(
        (ROOT / "eval" / "golden" / f"requirements_{args.vacancy}.json").read_text(encoding="utf-8")
    )
    vac = load_document(vpath.read_bytes(), vpath.name, DocKind.vacancy, args.vacancy)
    vtext = {f.id: f.text for f in vac.fragments}

    print(f"=== Вакансия {args.vacancy}: {vpath.name}")
    for i, item in enumerate(reqs["items"]):
        src = " | ".join(vtext.get(fid, "?") for fid in item["fragment_ids"])
        print(
            f"[{i:2}] {item['modality']:4} {item['kind']:10} {item['key']}\n      вакансия: {src}"
        )

    resume = load_document(rpath.read_bytes(), rpath.name, DocKind.resume, "R")
    print(f"\n=== Резюме {args.resume}: {rpath.name}")
    for f in resume.fragments:
        print(f"{f.id:>5} {{{f.section_role or '-'}}} {f.text}")

    if args.template:
        SECOND.mkdir(parents=True, exist_ok=True)
        out = SECOND / f"verdicts_{args.resume}_{args.vacancy}.json"
        if out.exists():
            print(f"\n{out} уже есть — не перезаписываю", file=sys.stderr)
            return 1
        template = {
            "resume_file": rpath.name,
            "vacancy_file": vpath.name,
            "annotator": "",
            "note": "Вторая независимая разметка по рубрике T07 и D43",
            "items": [
                {"key": it["key"], "status": "", "fragment_ids": [], "evidence_type": None}
                for it in reqs["items"]
            ],
        }
        out.write_text(
            json.dumps(template, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"\nшаблон: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
