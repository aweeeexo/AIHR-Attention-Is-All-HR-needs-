"""Dockerfile без литеральных «\\n» и висящих продолжений строк: жюри собирает образ как есть."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKSLASH_N = chr(92) + "n"  # два символа: обратная косая и n


def test_dockerfile_has_no_literal_newline_escapes() -> None:
    paths = [p for p in [ROOT / "Dockerfile", *ROOT.glob("*/Dockerfile")] if p.is_file()]
    if not paths:  # внутри тестового образа Dockerfile нет — проверяем в репозитории и в CI
        pytest.skip("Dockerfile не скопирован в окружение тестов")
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                continue
            assert BACKSLASH_N not in line, f"{path}:{i}: литеральный \\n вместо переноса строки"
            if line.rstrip().endswith(chr(92)):
                nxt = lines[i] if i < len(lines) else ""
                assert nxt.strip(), f"{path}:{i}: продолжение строки ведёт в пустую строку"
