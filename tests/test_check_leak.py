import importlib.util
import sys
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

_spec = importlib.util.spec_from_file_location(
    "check_leak", REPO_ROOT / "scripts" / "check_leak.py"
)
assert _spec and _spec.loader
check_leak = importlib.util.module_from_spec(_spec)
sys.modules["check_leak"] = check_leak
_spec.loader.exec_module(check_leak)


def _hits(text: str, *patterns: str, tmp_path: Path) -> list[str]:
    f = tmp_path / "prompt.md"
    f.write_text(text, encoding="utf-8")
    compiled = [(p, check_leak.compile_pattern(p)) for p in patterns]
    return [h.match for h in check_leak.scan([tmp_path], compiled)]


def test_prefix_and_phrase_patterns(tmp_path: Path) -> None:
    text = "Опыт куратора и учёт Основных  средств"
    assert _hits(text, "куратор*", "основн* средств*", tmp_path=tmp_path) == [
        "куратора",
        "Основных  средств",
    ]


@pytest.mark.parametrize(
    ("text", "pattern"),
    [("value", "Vue*"), ("space", "SPA"), ("access", "CSS*"), ("ssrf", "SSR")],
)
def test_no_match_inside_other_words(tmp_path: Path, text: str, pattern: str) -> None:
    assert _hits(text, pattern, tmp_path=tmp_path) == []


def test_exit_code(tmp_path: Path) -> None:
    words = tmp_path / "words.txt"
    words.write_text("# комментарий\nкуратор*\n", encoding="utf-8")
    clean, dirty = tmp_path / "clean", tmp_path / "dirty"
    clean.mkdir()
    dirty.mkdir()
    (clean / "a.py").write_text("x = 1\n", encoding="utf-8")
    (dirty / "a.md").write_text("Ты — куратор\n", encoding="utf-8")
    assert check_leak.main([str(clean), "--words", str(words)]) == 0
    assert check_leak.main([str(dirty), "--words", str(words)]) == 1


def test_src_has_no_case_words() -> None:
    patterns = check_leak.load_patterns(check_leak.DEFAULT_WORDS)
    hits = check_leak.scan(check_leak.DEFAULT_PATHS, patterns)
    assert not hits, [f"{h.path.name}:{h.line_no} {h.match}" for h in hits]
