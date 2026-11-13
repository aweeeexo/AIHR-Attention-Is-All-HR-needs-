"""Согласие двух разметчиков (T10): каппа Коэна по статусам для пар из eval/golden/second/.

    uv run python eval/agreement.py

Сравнивает eval/golden/verdicts_R?_V?.json (первая разметка) и eval/golden/second/ (вторая)
по пунктам с одинаковым ключом. Пустой статус во второй разметке — пункт не размечен, пропускаем.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden"
STATUSES = ["match", "partial", "mismatch", "not_stated"]


def kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    if not n:
        return 0.0
    observed = sum(a == b for a, b in pairs) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[s] * second[s] for s in STATUSES) / (n * n)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    pairs: list[tuple[str, str]] = []
    disagreements: list[str] = []
    for second_path in sorted((GOLDEN / "second").glob("verdicts_R*_V*.json")):
        first_path = GOLDEN / second_path.name
        if not first_path.exists():
            print(f"{second_path.name}: нет первой разметки, пропускаем")
            continue
        first = {i["key"]: i["status"] for i in json.loads(first_path.read_text("utf-8"))["items"]}
        for item in json.loads(second_path.read_text("utf-8"))["items"]:
            if not item["status"] or item["key"] not in first:
                continue
            if item["status"] not in STATUSES:
                print(
                    f"{second_path.name}: неизвестный статус «{item['status']}» у «{item['key']}»"
                )
                return 1
            pairs.append((first[item["key"]], item["status"]))
            if first[item["key"]] != item["status"]:
                disagreements.append(
                    f"  {second_path.stem[9:]}: {item['key']} — "
                    f"первая {first[item['key']]}, вторая {item['status']}"
                )
    if not pairs:
        print("Нет второй разметки: eval/golden/second/ пуст (см. scripts/label_pair.py).")
        return 0
    agree, n = sum(a == b for a, b in pairs), len(pairs)
    print(f"Пунктов: {n}, совпало: {agree} ({agree / n:.0%}), κ = {kappa(pairs):.2f}")
    print("Ориентир: κ ≥ 0.6 — хорошее согласие, ≥ 0.8 — отличное.")
    if disagreements:
        print("Расхождения (обсудить и при необходимости уточнить рубрику):")
        print("\n".join(disagreements))
    return 0


if __name__ == "__main__":
    sys.exit(main())
