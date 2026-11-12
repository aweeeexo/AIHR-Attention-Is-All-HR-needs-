"""Складывает набор плохих файлов из tests/bad_files.py в tests/fixtures/bad_files/ (для демо).

Запуск: uv run python scripts/make_bad_files.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.bad_files import BAD_FILES  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "bad_files"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["| Файл | Как загружать | Ожидаем |", "|---|---|---|"]
    for bf in BAD_FILES:
        (OUT / bf.name).write_bytes(bf.make())
        expected = (
            bf.code.value
            if bf.code
            else (f"предупреждение «{bf.warning}»" if bf.warning else "читается")
        )
        lines.append(
            f"| `{bf.name}` | {bf.kind.value} | {expected} {('— ' + bf.note) if bf.note else ''} |"
        )
    readme = (
        "# Плохие и нестандартные файлы\n\nСгенерированы `scripts/make_bad_files.py`.\n\n"
        + "\n".join(lines)
        + "\n"
    )
    (OUT / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    sys.stdout.write(f"записано файлов: {len(BAD_FILES)} в {OUT}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
