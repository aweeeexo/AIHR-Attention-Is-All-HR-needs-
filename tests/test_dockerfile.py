"""Dockerfile без литеральных «\\n» и висящих продолжений строк: жюри собирает образ как есть."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKSLASH_N = chr(92) + "n"  # два символа: обратная косая и n


def test_dockerfile_has_no_literal_newline_escapes() -> None:
    for path in [ROOT / "Dockerfile", *ROOT.glob("*/Dockerfile")]:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith("#"):
                continue
            assert BACKSLASH_N not in line, f"{path}:{i}: литеральный \\n вместо переноса строки"
            if line.rstrip().endswith(chr(92)):
                nxt = lines[i] if i < len(lines) else ""
                assert nxt.strip(), f"{path}:{i}: продолжение строки ведёт в пустую строку"
