"""Метрики на отложенном наборе (D57).

    uv run python eval/holdout/run.py [--src путь/к/src] [--out файл.json]

--src — чей код считать (например, git worktree с main), чтобы сравнить до и после на одних
документах. Ложные «Соответствует» — «Соответствует» там, где по разметке что-то другое.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "src"))
    ap.add_argument("--out")
    args = ap.parse_args()
    sys.path.insert(0, args.src)
    sys.path.insert(1, str(ROOT / "eval"))
    # aihr — до requirements_eval: тот при импорте ставит в sys.path свой src
    import aihr  # noqa: I001 — порядок важен, см. комментарий выше
    from aihr.config import Settings
    from aihr.inputs import read_files
    from aihr.pipeline import run
    from requirements_eval import evaluate

    print(f"код: {Path(aihr.__file__).parent}", file=sys.stderr)

    settings = Settings(_env_file=ROOT / ".env")  # type: ignore[call-arg]
    docs, golden = HERE / "docs", HERE / "golden"
    reqs_gold = {
        (g := json.loads(p.read_text(encoding="utf-8")))["vacancy_file"]: g
        for p in sorted(golden.glob("requirements_*.json"))
    }
    pairs: dict[str, list[dict]] = {}
    for p in sorted(golden.glob("verdicts_*.json")):
        g = json.loads(p.read_text(encoding="utf-8"))
        pairs.setdefault(g["resume_file"], []).append(g)

    rows, req_total, req_matched = [], 0, 0
    for rfile, labels in pairs.items():
        vfiles = [g["vacancy_file"] for g in labels]
        result = run(read_files([docs / rfile])[0], read_files([docs / v for v in vfiles]),
                     settings=settings, save=False)  # fmt: skip
        files = {v.id: v.filename for v in result.vacancies}
        for vid, reqs in result.requirements.items():
            g = next(x for x in labels if x["vacancy_file"] == files[vid])
            score = evaluate(reqs_gold[files[vid]], reqs)
            if rfile == next(iter(pairs)) or files[vid] == "Вакансия H4.txt":
                req_total += score.golden
                req_matched += score.matched
            verdicts = {v.requirement_id: v for v in result.verdicts.get(vid, [])}
            for gi, item in enumerate(g["items"]):
                ri = score.matches.get(gi)
                pred = verdicts[reqs[ri].id].status.value if ri is not None else "not_stated"
                rows.append({"pair": f"{rfile.split()[-1][:-4]}×{files[vid].split()[-1][:-4]}",
                             "key": item["key"], "gold": item["status"], "pred": pred,
                             "req": reqs[ri].text if ri is not None else None})  # fmt: skip

    statuses = ["match", "partial", "mismatch", "not_stated"]
    f1 = []
    for st in statuses:
        tp = sum(r["gold"] == st and r["pred"] == st for r in rows)
        fp = sum(r["gold"] != st and r["pred"] == st for r in rows)
        fn = sum(r["gold"] == st and r["pred"] != st for r in rows)
        if tp + fp + fn:
            pr, rc = (tp / (tp + fp) if tp + fp else 0), (tp / (tp + fn) if tp + fn else 0)
            f1.append(2 * pr * rc / (pr + rc) if pr + rc else 0)
    summary = {
        "items": len(rows),
        "accuracy": round(sum(r["gold"] == r["pred"] for r in rows) / len(rows), 3),
        "macro_f1": round(sum(f1) / len(f1), 3),
        "false_match": sum(r["pred"] == "match" and r["gold"] != "match" for r in rows),
        "false_mismatch": sum(r["pred"] == "mismatch" and r["gold"] == "not_stated" for r in rows),
        "requirements_recall": f"{req_matched}/{req_total}",
    }
    print(json.dumps(summary, ensure_ascii=False))
    if args.out:
        report = json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1)
        Path(args.out).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
