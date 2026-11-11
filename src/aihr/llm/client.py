"""Единственная точка выхода к LLM (принцип 4, D10).

T00: загрузка промпта, вызов через openai SDK, разбор JSON, проверка схемой, повтор с текстом
ошибки. T03 добавит guard на ПДн, журнал исходящих, кэш, режимы structured output и семафор.

До T02 сюда не отправляем резюме кейса: маскирование ещё не готово.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from aihr.config import Settings, get_settings
from aihr.contracts import LLMBadOutput, LLMUnavailable
from aihr.llm.prompting import render_prompt

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_FIX_ATTEMPTS = 2  # повторы при невалидном JSON

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _schema_instruction(schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return (
        "Ответь одним JSON-объектом без пояснений и без markdown. "
        f"Объект должен соответствовать JSON-схеме:\n{schema_json}"
    )


def _extract_json(content: str) -> Any:
    text = content.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1)
    return json.loads(text)


class LLMClient:
    """`structured(prompt_id, variables, schema)` → объект схемы или исключение.

    `client` — подмена openai.OpenAI в тестах: любой объект с `.chat.completions.create(...)`.
    """

    def __init__(self, settings: Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None or self.settings.llm_configured

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        s = self.settings
        if not s.llm_configured:
            raise LLMUnavailable("LLM не настроена: нужны LLM_BASE_URL и LLM_MODEL")
        # Локальным серверам ключ не нужен, а SDK требует непустой
        api_key = s.llm_api_key.get_secret_value() if s.llm_api_key else "not-needed"
        self._client = openai.OpenAI(
            base_url=s.llm_base_url,
            api_key=api_key,
            project=s.llm_project or None,
            timeout=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
        )
        return self._client

    def structured(self, prompt_id: str, variables: dict[str, Any], schema: type[T]) -> T:
        if self.settings.llm_provider == "none" and self._client is None:
            raise LLMUnavailable("LLM_PROVIDER=none")
        client = self._get_client()
        prompt = render_prompt(prompt_id, variables)

        system = _schema_instruction(schema)
        if prompt.system:
            system = f"{prompt.system}\n\n{system}"
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt.user},
        ]

        last_error = ""
        for attempt in range(MAX_FIX_ATTEMPTS + 1):
            content = self._complete(client, messages, prompt_id)
            try:
                return schema.model_validate(_extract_json(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = str(exc)[:2000]
                log.warning(
                    "%s: ответ не прошёл схему %s (попытка %d)",
                    prompt_id,
                    schema.__name__,
                    attempt + 1,
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "Ответ не прошёл проверку схемы. Ошибка:\n"
                        f"{last_error}\nВерни исправленный JSON целиком.",
                    },
                ]
        raise LLMBadOutput(f"{prompt_id}: ответ не прошёл схему {schema.__name__}: {last_error}")

    def _complete(self, client: Any, messages: list[dict[str, str]], prompt_id: str) -> str:
        started = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except openai.APIStatusError as exc:
            raise LLMUnavailable(f"{prompt_id}: провайдер вернул HTTP {exc.status_code}") from exc
        except openai.APIError as exc:
            raise LLMUnavailable(f"{prompt_id}: {type(exc).__name__}") from exc
        log.info("%s: ответ за %d мс", prompt_id, (time.perf_counter() - started) * 1000)
        content = response.choices[0].message.content
        if not content:
            raise LLMBadOutput(f"{prompt_id}: пустой ответ модели")
        return content
