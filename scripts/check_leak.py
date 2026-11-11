"""check-leak: ищет слова из вакансий кейса в src/ (код и промпты). Принцип 5, D12.

Запуск: `uv run poe check-leak` (или `make check-leak`). Ненулевой код выхода — найдены совпадения.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORDS = ROOT / "scripts" / "leak_words.txt"
DEFAULT_PATHS = [ROOT / "src"]
SCANNED_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".j2", ".jinja"}


@dataclass(frozen=True)
class Hit:
    path: Path
    line_no: int
    pattern: str
    match: str


def compile_pattern(raw: str) -> re.Pattern[str]:
    parts = [re.escape(p).replace(r"\*", r"\w*") for p in raw.split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)


def load_patterns(words_file: Path) -> list[tuple[str, re.Pattern[str]]]:
    patterns = []
    for line in words_file.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if raw and not raw.startswith("#"):
            patterns.append((raw, compile_pattern(raw)))
    return patterns


def iter_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for base in paths:
        if base.is_file():
            files.append(base)
        elif base.is_dir():
            files.extend(
                p
                for p in sorted(base.rglob("*"))
                if p.is_file() and p.suffix.lower() in SCANNED_SUFFIXES
            )
    return files


def scan(paths: list[Path], patterns: list[tuple[str, re.Pattern[str]]]) -> list[Hit]:
    hits: list[Hit] = []
    for path in iter_files(paths):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for raw, pattern in patterns:
                for m in pattern.finditer(line):
                    hits.append(Hit(path, line_no, raw, m.group(0)))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=DEFAULT_PATHS)
    parser.add_argument("--words", type=Path, default=DEFAULT_WORDS)
    args = parser.parse_args(argv)

    patterns = load_patterns(args.words)
    hits = scan(args.paths, patterns)
    out = sys.stdout
    for hit in hits:
        try:
            shown = hit.path.relative_to(ROOT)
        except ValueError:
            shown = hit.path
        out.write(f"{shown}:{hit.line_no}: «{hit.match}» (шаблон «{hit.pattern}»)\n")
    if hits:
        out.write(f"check-leak: найдено совпадений: {len(hits)}\n")
        return 1
    out.write(
        f"check-leak: чисто ({len(patterns)} шаблонов, {len(iter_files(args.paths))} файлов)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
