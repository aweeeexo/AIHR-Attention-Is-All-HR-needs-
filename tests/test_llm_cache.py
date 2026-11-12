"""T03: кэш, режимы structured output, семафор, учёт, параллельный пайплайн."""

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from aihr import pipeline
from aihr.config import Settings
from aihr.llm import LLMClient
from aihr.llm import client as client_module
from aihr.llm.client import _extract_json
from aihr.llm.prompting import RenderedPrompt
from aihr.privacy import PrivacyContext
from aihr.privacy.outbound import OutboundLog
from tests.conftest import FakeOpenAI, fixture_file
from tests.test_llm_client import Ping

OK = '{"ok": true, "word": "сосна"}'


def _settings(**kw: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_base_url="http://llm.invalid/v1",
        llm_model="test-model",
        **kw,
    )


@pytest.fixture(autouse=True)
def _reset_json_schema_memory() -> None:
    LLMClient._no_json_schema.clear()


# ---------- кэш ----------


def test_second_call_comes_from_cache(tmp_path: Path) -> None:
    fake = FakeOpenAI([OK])
    log = OutboundLog(tmp_path / "out.jsonl")
    llm = LLMClient(_settings(), client=fake).for_run(PrivacyContext(), log)
    first = llm.structured("llm/ping", {"word": "сосна"}, Ping)
    second = llm.structured("llm/ping", {"word": "сосна"}, Ping)
    assert first == second
    assert len(fake.completions.calls) == 1  # второй раз наружу не ходили
    entries = [json.loads(x) for x in log.path.read_text(encoding="utf-8").splitlines()]
    assert [e["cached"] for e in entries] == [False, True]
    assert llm.stats.requests == 1 and llm.stats.cache_hits == 1


def test_cache_survives_new_client() -> None:
    LLMClient(_settings(), client=FakeOpenAI([OK])).structured("llm/ping", {"word": "x"}, Ping)
    fake = FakeOpenAI([])
    LLMClient(_settings(), client=fake).structured("llm/ping", {"word": "x"}, Ping)
    assert fake.completions.calls == []


def test_different_input_misses_cache() -> None:
    fake = FakeOpenAI([OK, OK])
    llm = LLMClient(_settings(), client=fake)
    llm.structured("llm/ping", {"word": "сосна"}, Ping)
    llm.structured("llm/ping", {"word": "ель"}, Ping)
    assert len(fake.completions.calls) == 2


def test_prompt_version_change_misses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeOpenAI([OK, OK])
    llm = LLMClient(_settings(), client=fake)
    llm.structured("llm/ping", {"word": "сосна"}, Ping)
    real = client_module.render_prompt

    def bumped(prompt_id: str, variables: dict[str, Any]) -> RenderedPrompt:
        r = real(prompt_id, variables)
        return RenderedPrompt(r.prompt_id, r.version + 1, r.system, r.user)

    monkeypatch.setattr(client_module, "render_prompt", bumped)
    llm.structured("llm/ping", {"word": "сосна"}, Ping)
    assert len(fake.completions.calls) == 2


def test_model_change_misses_cache() -> None:
    LLMClient(_settings(), client=FakeOpenAI([OK])).structured("llm/ping", {"word": "x"}, Ping)
    fake = FakeOpenAI([OK])
    other = _settings().model_copy(update={"llm_model": "other-model"})
    LLMClient(other, client=fake).structured("llm/ping", {"word": "x"}, Ping)
    assert len(fake.completions.calls) == 1


def test_cache_can_be_disabled() -> None:
    fake = FakeOpenAI([OK, OK])
    llm = LLMClient(_settings(llm_cache=False), client=fake)
    llm.structured("llm/ping", {"word": "x"}, Ping)
    llm.structured("llm/ping", {"word": "x"}, Ping)
    assert len(fake.completions.calls) == 2


def test_failed_answers_are_not_cached() -> None:
    fake = FakeOpenAI(["не json"] * 3 + [OK])
    llm = LLMClient(_settings(), client=fake)
    with pytest.raises(Exception, match="схему"):
        llm.structured("llm/ping", {"word": "x"}, Ping)
    assert llm.structured("llm/ping", {"word": "x"}, Ping).ok
    assert len(fake.completions.calls) == 4


# ---------- structured output ----------


def _bad_request() -> openai.BadRequestError:
    request = httpx.Request("POST", "http://llm.invalid/v1/chat/completions")
    return openai.BadRequestError(
        "json_schema not supported", response=httpx.Response(400, request=request), body=None
    )


def test_auto_mode_falls_back_to_json_object_and_remembers() -> None:
    fake = FakeOpenAI([_bad_request(), OK, OK])
    llm = LLMClient(_settings(llm_cache=False), client=fake)
    assert llm.structured("llm/ping", {"word": "x"}, Ping).ok
    assert llm.structured("llm/ping", {"word": "y"}, Ping).ok
    formats = [c["response_format"]["type"] for c in fake.completions.calls]
    assert formats == ["json_schema", "json_object", "json_object"]


def test_explicit_json_schema_mode_does_not_fall_back() -> None:
    fake = FakeOpenAI([_bad_request()])
    llm = LLMClient(_settings(llm_structured_mode="json_schema"), client=fake)
    with pytest.raises(Exception, match="400"):
        llm.structured("llm/ping", {"word": "x"}, Ping)


def test_json_object_mode() -> None:
    fake = FakeOpenAI([OK])
    LLMClient(_settings(llm_structured_mode="json_object"), client=fake).structured(
        "llm/ping", {"word": "x"}, Ping
    )
    assert fake.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_schema_is_always_in_system_message() -> None:
    fake = FakeOpenAI([OK])
    LLMClient(_settings(), client=fake).structured("llm/ping", {"word": "x"}, Ping)
    call = fake.completions.calls[0]
    assert call["response_format"]["type"] == "json_schema"
    assert '"word"' in call["messages"][0]["content"]  # схема текстом — для прокси


def test_extract_json_with_surrounding_text() -> None:
    assert _extract_json('Вот ответ:\n{"ok": true, "word": "x"}\nГотово.') == {
        "ok": True,
        "word": "x",
    }


# ---------- учёт и параллельность ----------


def test_usage_is_counted() -> None:
    class WithUsage(FakeOpenAI):
        pass

    fake = WithUsage([OK])
    original = fake.completions.create

    def create(**kwargs: Any) -> Any:
        r = original(**kwargs)
        r.usage = SimpleNamespace(prompt_tokens=120, completion_tokens=15)
        return r

    fake.completions.create = create  # type: ignore[method-assign]
    llm = LLMClient(_settings(), client=fake)
    llm.structured("llm/ping", {"word": "x"}, Ping)
    timings = llm.stats.as_timings()
    assert timings["llm_prompt_tokens"] == 120 and timings["llm_completion_tokens"] == 15
    assert timings["llm_requests"] == 1


class SlowFake:
    """Отвечает с задержкой и считает, сколько запросов было одновременно."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs: Any) -> Any:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        word = json.loads(kwargs["messages"][1]["content"].split()[-1].join('""'))
        msg = SimpleNamespace(content=json.dumps({"ok": True, "word": word}))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.mark.parametrize("concurrency", [1, 2])
def test_semaphore_limits_parallel_requests(concurrency: int) -> None:
    fake = SlowFake()
    llm = LLMClient(_settings(llm_concurrency=concurrency, llm_cache=False), client=fake)
    threads = [
        threading.Thread(target=llm.structured, args=("llm/ping", {"word": f"w{i}"}, Ping))
        for i in range(6)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert fake.max_active <= concurrency
    assert llm.stats.requests == 6


def test_pipeline_parallel_keeps_order_and_reports_llm_stats(llm_settings) -> None:  # noqa: ANN001
    s = llm_settings.model_copy(update={"llm_concurrency": 3})
    llm = LLMClient(s, client=FakeOpenAI([]))
    vacancies = [fixture_file("vacancy_cook.txt"), fixture_file("vacancy_welder.txt")] * 2
    r = pipeline.run(fixture_file("resume_cook.txt"), vacancies, settings=s, llm=llm)
    assert [v.id for v in r.vacancies] == ["V1", "V2", "V3", "V4"]
    assert set(r.reports) == {"V1", "V2", "V3", "V4"}
    assert "llm_requests" in r.timings_ms and "llm_cache_hits" in r.timings_ms
