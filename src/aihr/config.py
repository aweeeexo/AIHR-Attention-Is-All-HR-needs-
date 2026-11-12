"""Настройки из окружения (и из `.env`, если он есть в текущей папке).

Относительные пути считаются от текущей папки: в контейнере это /app, локально — корень репозитория.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aihr.contracts import YearMonth

# Пустое значение этих переменных что-то выключает, поэтому "" не заменяем значением по умолчанию
_EMPTY_MEANS_OFF = {"embeddings_model"}

_TODAY_RE = re.compile(r"^(\d{4})-(\d{2})$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # replay — запросы и ответы через файлы, пока нет API (D39, src/aihr/llm/replay.py)
    llm_provider: Literal["openai_compatible", "replay", "none"] = "openai_compatible"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    # Своя модель для отдельных шагов: "extract/profile=<модель>,report/questions=<модель>".
    # Ключ — prompt_id или его начало («extract/» — все шаги извлечения). Провайдер тот же (D46)
    llm_model_routes: str = ""
    llm_project: str | None = None
    llm_timeout_s: float = Field(default=60, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    llm_concurrency: int = Field(default=4, ge=1)
    # Предел длины ответа. Пусто — по умолчанию провайдера; у части провайдеров он мал, и длинный
    # JSON обрывается на середине
    llm_max_tokens: int | None = Field(default=None, ge=1)
    # auto — пробуем json_schema, при отказе провайдера переходим на json_object
    llm_structured_mode: Literal["auto", "json_schema", "json_object"] = "auto"
    llm_cache: bool = True  # кэш ответов по хэшу запроса (D17)
    llm_replay_dir: Path = Path("data/llm_replay")
    llm_replay_wait_s: float = Field(default=0, ge=0)  # сколько ждать ответ в режиме replay

    embeddings_model: str | None = "intfloat/multilingual-e5-small"

    max_file_mb: float = Field(default=10, gt=0)
    max_batch_resumes: int = Field(default=50, ge=1)  # резюме в одном пакете (D38)
    runs_dir: Path = Path("data/runs")
    cache_dir: Path = Path("data/cache")
    case_dir: Path = Path("data/case")
    scoring_config: Path = Path("config/scoring.yaml")
    synonyms_path: Path = Path("data/synonyms.yaml")
    today: str | None = None  # "2026-11" — фиксированная дата для воспроизводимых тестов
    log_level: str = "INFO"

    api_url: str = "http://localhost:8000"  # куда ходит UI
    # Откуда браузерный веб-интерфейс может ходить в API (через запятую; "*" — откуда угодно)
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:8501"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="before")
    @classmethod
    def _empty_to_default(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str) and value.strip() == "":
                if key.lower() in _EMPTY_MEANS_OFF:
                    cleaned[key] = None
                continue
            cleaned[key] = value
        return cleaned

    @field_validator("today")
    @classmethod
    def _check_today(cls, value: str | None) -> str | None:
        if value is None:
            return None
        m = _TODAY_RE.match(value.strip())
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise ValueError("TODAY должен быть в формате ГГГГ-ММ, например 2026-11")
        return value.strip()

    def model_for(self, prompt_id: str) -> str | None:
        """Модель для шага: самый длинный подходящий маршрут, иначе LLM_MODEL."""
        best, model = -1, self.llm_model
        for item in self.llm_model_routes.split(","):
            key, sep, value = item.partition("=")
            key, value = key.strip(), value.strip()
            if sep and key and value and prompt_id.startswith(key) and len(key) > best:
                best, model = len(key), value
        return model

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "replay":
            return bool(self.llm_model)
        return self.llm_provider == "openai_compatible" and bool(
            self.llm_base_url and self.llm_model
        )

    @property
    def mode(self) -> Literal["llm", "fallback"]:
        return "llm" if self.llm_configured else "fallback"

    @property
    def max_file_bytes(self) -> int:
        return int(self.max_file_mb * 1024 * 1024)

    def today_ym(self) -> YearMonth:
        if self.today:
            year, month = self.today.split("-")
            return YearMonth(year=int(year), month=int(month))
        now = date.today()
        return YearMonth(year=now.year, month=now.month)


@lru_cache
def get_settings() -> Settings:
    # AIHR_ENV_FILE нужен тестам, чтобы не читать локальный .env с настоящим ключом
    env_file = os.environ.get("AIHR_ENV_FILE", ".env")
    return Settings(_env_file=env_file or None)  # type: ignore[call-arg]


# Сторонние библиотеки шумят на INFO и предупреждают об офлайн-режиме, который мы включили сами
_QUIET = ("huggingface_hub", "sentence_transformers", "transformers", "pymorphy2", "httpx")


def setup_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=(level or get_settings().log_level).upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if (level or "").upper() != "DEBUG":
        for name in _QUIET:
            logging.getLogger(name).setLevel(logging.ERROR)
