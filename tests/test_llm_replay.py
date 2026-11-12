"""D39: провайдер replay — запросы в очередь файлами, ответы из файлов."""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from aihr.config import Settings
from aihr.contracts import LLMUnavailable
from aihr.llm import LLMClient
from aihr.pipeline import run
from tests.conftest import FakeOpenAI, fixture_file


class Ping(BaseModel):
    ok: bool
    word: str


def _settings(tmp_path: Path, wait: float = 0) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_provider="replay",
        llm_model="replay-test",
        llm_replay_dir=tmp_path / "replay",
        llm_replay_wait_s=wait,
        cache_dir=tmp_path / "cache",
    )


def test_replay_queues_then_answers(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert s.llm_configured and s.mode == "llm"
    with pytest.raises(LLMUnavailable):
        LLMClient(s).structured("llm/ping", {"word": "проверка"}, Ping)
    [queued] = list((tmp_path / "replay" / "queue").glob("*.json"))
    request = json.loads(queued.read_text(encoding="utf-8"))
    assert (
        request["messages"][0]["role"] == "system"
        and "проверка" in request["messages"][1]["content"]
    )
    Path(request["answer_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(request["answer_path"]).write_text('{"ok": true, "word": "проверка"}', encoding="utf-8")

    got = LLMClient(s).structured("llm/ping", {"word": "проверка"}, Ping)
    assert got == Ping(ok=True, word="проверка")
    assert not queued.exists()


def test_replay_without_model_is_not_configured(tmp_path: Path) -> None:
    s = _settings(tmp_path).model_copy(update={"llm_model": None})
    assert not s.llm_configured


def test_bad_llm_output_on_profile_does_not_crash_run(llm_settings: Settings) -> None:
    llm = LLMClient(llm_settings, client=FakeOpenAI(["не json"] * 100))
    result = run(
        fixture_file("resume_cook.txt"),
        [fixture_file("vacancy_cook.txt")],
        settings=llm_settings,
        llm=llm,
        save=False,
    )
    assert result.profile is not None and result.ranking is not None
    assert any("не прошёл проверку схемы" in w for w in result.warnings)


def test_single_llm_failure_keeps_llm_mode(llm_settings: Settings) -> None:
    """Один сбой LLM — только этот шаг без LLM, прогон остаётся в режиме LLM."""
    import httpx
    import openai

    from tests.conftest import EchoRequirementsLLM

    echo = EchoRequirementsLLM()
    calls = {"n": 0}
    original = echo.create

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # профиль кандидата
            raise openai.APITimeoutError(request=httpx.Request("POST", "http://x/v1"))
        return original(**kwargs)

    echo.create = flaky
    s = llm_settings.model_copy(update={"llm_max_retries": 0})
    result = run(
        fixture_file("resume_cook.txt"),
        [fixture_file("vacancy_cook.txt")],
        settings=s,
        llm=LLMClient(s, client=echo),
        save=False,
    )
    assert result.mode == "llm"
    assert any("на одном шаге" in w for w in result.warnings)
    assert calls["n"] > 1  # дальше шли запросы к LLM
