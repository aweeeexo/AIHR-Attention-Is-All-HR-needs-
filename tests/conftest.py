"""Общие фикстуры. Тесты не ходят в сеть: openai SDK подменяется заглушкой."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aihr.config import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = REPO_ROOT / "data" / "case"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Каждый тест видит только настройки по умолчанию, без локального .env и переменных машины."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("AIHR_ENV_FILE", "")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("CASE_DIR", str(CASE_DIR))
    monkeypatch.setenv("SCORING_CONFIG", str(REPO_ROOT / "config" / "scoring.yaml"))
    monkeypatch.setenv("TODAY", "2026-11")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeCompletions:
    """Заменяет client.chat.completions: отдаёт заготовленные ответы и запоминает запросы."""

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        message = SimpleNamespace(content=reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOpenAI:
    def __init__(self, replies: list[str | Exception]) -> None:
        self.completions = FakeCompletions(replies)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.fixture
def llm_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_base_url="http://llm.invalid/v1",
        llm_model="test-model",
    )


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_file(name: str) -> tuple[bytes, str]:
    path = FIXTURES / name
    return path.read_bytes(), path.name


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    import io

    import docx

    d = docx.Document()
    for text in paragraphs:
        d.add_paragraph(text)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, text in enumerate(row):
                t.cell(r, c).text = text
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
