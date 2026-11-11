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

    llm_provider: Literal["openai_compatible", "none"] = "openai_compatible"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_project: str | None = None
    llm_timeout_s: float = Field(default=60, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    llm_concurrency: int = Field(default=4, ge=1)

    embeddings_model: str | None = "intfloat/multilingual-e5-small"

    max_file_mb: float = Field(default=10, gt=0)
    runs_dir: Path = Path("data/runs")
    case_dir: Path = Path("data/case")
    scoring_config: Path = Path("config/scoring.yaml")
    today: str | None = None  # "2026-11" — фиксированная дата для воспроизводимых тестов
    log_level: str = "INFO"

    api_url: str = "http://localhost:8000"  # куда ходит UI

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

    @property
    def llm_configured(self) -> bool:
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


def setup_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=(level or get_settings().log_level).upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
