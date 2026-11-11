import pytest
from pydantic import ValidationError

from aihr.config import Settings, get_settings
from aihr.contracts import YearMonth


def _settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def test_defaults_without_llm() -> None:
    s = _settings()
    assert s.llm_provider == "openai_compatible"
    assert not s.llm_configured
    assert s.mode == "fallback"
    assert s.embeddings_model == "intfloat/multilingual-e5-small"
    assert s.max_file_bytes == 10 * 1024 * 1024


def test_empty_values_from_env_file_become_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_TIMEOUT_S", "")
    monkeypatch.setenv("LLM_CONCURRENCY", " ")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.llm_base_url is None
    assert s.llm_timeout_s == 60
    assert s.llm_concurrency == 4


def test_empty_embeddings_model_disables_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDINGS_MODEL", "")
    assert Settings(_env_file=None).embeddings_model is None  # type: ignore[call-arg]


def test_llm_configured_and_none_provider() -> None:
    s = _settings(llm_base_url="http://x/v1", llm_model="m")
    assert s.llm_configured and s.mode == "llm"
    s = _settings(llm_base_url="http://x/v1", llm_model="m", llm_provider="none")
    assert not s.llm_configured and s.mode == "fallback"


def test_api_key_is_hidden() -> None:
    s = _settings(llm_api_key="sk-very-secret")
    assert "sk-very-secret" not in repr(s)
    assert "sk-very-secret" not in s.model_dump_json()


def test_today() -> None:
    assert _settings(today="2026-11").today_ym() == YearMonth(year=2026, month=11)
    with pytest.raises(ValidationError):
        _settings(today="2026-13")
    with pytest.raises(ValidationError):
        _settings(today="ноябрь")


def test_get_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "from-env")
    get_settings.cache_clear()
    assert get_settings().llm_model == "from-env"
