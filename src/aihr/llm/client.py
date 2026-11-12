"""Единственная точка выхода к LLM (принцип 4, D10).

Порядок одного вызова `structured()`:
промпт из файла → guard на ПДн (T02) → кэш (T03) → семафор → запрос через openai SDK →
разбор JSON → проверка схемой → при ошибке повтор с текстом ошибки (до 2 раз) → кэш.
Каждый запрос, попадание в кэш и блокировка пишутся в журнал исходящих (T02).

Режимы structured output (`LLM_STRUCTURED_MODE`): `json_schema`, `json_object` или `auto` —
пробуем json_schema, при отказе провайдера запоминаем и переходим на json_object. Схема всегда
дублируется текстом в системном сообщении: часть провайдеров (прокси веб-чатов) игнорирует
response_format.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from aihr.config import Settings, get_settings
from aihr.contracts import LLMBadOutput, LLMUnavailable, PrivacyViolation
from aihr.llm.prompting import RenderedPrompt, render_prompt
from aihr.privacy import PrivacyContext, check_outbound
from aihr.privacy.outbound import OutboundLog

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_FIX_ATTEMPTS = 2  # повторы при невалидном JSON
CACHE_FORMAT = 1  # меняем, если меняется формат записи в кэше

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}
_SEMAPHORES_LOCK = threading.Lock()


def _semaphore(n: int) -> threading.BoundedSemaphore:
    with _SEMAPHORES_LOCK:
        if n not in _SEMAPHORES:
            _SEMAPHORES[n] = threading.BoundedSemaphore(n)
        return _SEMAPHORES[n]


@lru_cache
def _open_cache(path: str) -> Any:
    import diskcache

    Path(path).mkdir(parents=True, exist_ok=True)
    return diskcache.Cache(path)


def _schema_json(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), ensure_ascii=False, sort_keys=True)


def _schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "Ответь одним JSON-объектом без пояснений и без markdown. "
        f"Объект должен соответствовать JSON-схеме:\n{_schema_json(schema)}"
    )


def _error_text(exc: Exception) -> str:
    """Ошибка для модели: поле и сообщение. Без ссылок pydantic — их заблокировал бы guard."""
    if isinstance(exc, ValidationError):
        lines = [
            f"{'.'.join(str(x) for x in e['loc']) or '<корень>'}: {e['msg']}" for e in exc.errors()
        ]
        return "\n".join(lines[:20])
    return str(exc)[:500]


def _extract_json(content: str) -> Any:
    text = content.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Модель добавила текст до или после объекта: берём от первой «{» до последней «}»
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            return json.loads(text[start : end + 1])
        raise


@dataclass
class LLMStats:
    """Учёт одного прогона: попадает в MatchResult.timings_ms с префиксом llm_."""

    requests: int = 0
    cache_hits: int = 0
    blocked: int = 0
    fixes: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    ms: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, **values: int) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(self, key, getattr(self, key) + value)

    def as_timings(self) -> dict[str, int]:
        return {
            "llm_requests": self.requests,
            "llm_cache_hits": self.cache_hits,
            "llm_blocked": self.blocked,
            "llm_fixes": self.fixes,
            "llm_prompt_tokens": self.prompt_tokens,
            "llm_completion_tokens": self.completion_tokens,
            "llm_ms": self.ms,
        }


class LLMClient:
    """`structured(prompt_id, variables, schema)` → объект схемы или исключение.

    `client` — подмена openai.OpenAI в тестах: любой объект с `.chat.completions.create(...)`.
    """

    # (base_url, model), которые не приняли response_format=json_schema — для режима auto
    _no_json_schema: ClassVar[set[tuple[str, str]]] = set()

    def __init__(
        self,
        settings: Settings | None = None,
        client: Any | None = None,
        privacy: PrivacyContext | None = None,
        outbound: OutboundLog | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.privacy = privacy
        self.outbound = outbound
        self.stats = LLMStats()

    def for_run(self, privacy: PrivacyContext, outbound: OutboundLog | None) -> LLMClient:
        """Клиент одного прогона: guard знает ФИО этого прогона, запросы пишутся в его журнал."""
        clone = LLMClient(self.settings, self._client, privacy, outbound)
        if self._client is None and self.settings.llm_configured:
            clone._client = self._get_client()  # одно соединение на все прогоны
        return clone

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
            max_retries=s.llm_max_retries,  # 429, 5xx и сеть — с экспоненциальной паузой
        )
        return self._client

    # ---------- основной вызов ----------

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
        self._guard(messages, prompt)

        key = self._cache_key(prompt, messages, schema)
        cached = self._cache_get(key)
        if cached is not None:
            try:
                result = schema.model_validate(cached)
            except ValidationError:
                result = None
            if result is not None:
                self.stats.add(cache_hits=1)
                self._log(prompt, status="ok", cached=True, messages=messages)
                return result

        last_error = ""
        for attempt in range(MAX_FIX_ATTEMPTS + 1):
            if attempt:
                self._guard(messages, prompt)
                self.stats.add(fixes=1)
            content = self._complete(client, messages, prompt, schema)
            try:
                result = schema.model_validate(_extract_json(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = _error_text(exc)
                log.warning(
                    "%s: ответ не прошёл схему %s (попытка %d)",
                    prompt.prompt_id,
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
                continue
            self._cache_set(key, result.model_dump(mode="json"))
            return result
        raise LLMBadOutput(
            f"{prompt.prompt_id}: ответ не прошёл схему {schema.__name__}: {last_error}"
        )

    # ---------- guard и журнал ----------

    def _guard(self, messages: list[dict[str, str]], prompt: RenderedPrompt) -> None:
        text = "\n".join(m["content"] for m in messages)
        try:
            check_outbound(text, self.privacy, prompt.prompt_id)
        except PrivacyViolation as exc:
            log.warning("%s", exc)  # без самих данных
            self.stats.add(blocked=1)
            self._log(prompt, status="blocked", reason=str(exc))
            raise

    def _log(self, prompt: RenderedPrompt, **entry: Any) -> None:
        if self.outbound:
            self.outbound.write(
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.version,
                model=self.settings.llm_model,
                **entry,
            )

    # ---------- кэш ----------

    def _cache_key(
        self, prompt: RenderedPrompt, messages: list[dict[str, str]], schema: type[BaseModel]
    ) -> str:
        parts = [
            str(CACHE_FORMAT),
            self.settings.llm_model or "",
            prompt.prompt_id,
            str(prompt.version),
            schema.__name__,
            hashlib.sha256(_schema_json(schema).encode()).hexdigest(),
            json.dumps(messages, ensure_ascii=False),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _cache(self) -> Any | None:
        if not self.settings.llm_cache:
            return None
        try:
            return _open_cache(str(self.settings.cache_dir.resolve()))
        except Exception as exc:  # кэш — ускорение, а не условие работы
            log.warning("кэш LLM недоступен: %s", type(exc).__name__)
            return None

    def _cache_get(self, key: str) -> Any | None:
        cache = self._cache()
        return cache.get(key) if cache is not None else None

    def _cache_set(self, key: str, value: Any) -> None:
        cache = self._cache()
        if cache is not None:
            cache.set(key, value)

    # ---------- запрос ----------

    def _response_format(self, schema: type[BaseModel]) -> dict[str, Any]:
        mode = self.settings.llm_structured_mode
        target = (self.settings.llm_base_url or "", self.settings.llm_model or "")
        if mode == "json_object" or (mode == "auto" and target in self._no_json_schema):
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            # strict=false: схемы pydantic с необязательными полями strict-режим не принимает
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
                "strict": False,
            },
        }

    def _complete(
        self,
        client: Any,
        messages: list[dict[str, str]],
        prompt: RenderedPrompt,
        schema: type[BaseModel],
    ) -> str:
        response_format = self._response_format(schema)
        started = time.perf_counter()
        try:
            with _semaphore(self.settings.llm_concurrency):
                response = self._create(client, messages, response_format)
        except (openai.BadRequestError, openai.UnprocessableEntityError) as exc:
            auto = self.settings.llm_structured_mode == "auto"
            if auto and response_format["type"] == "json_schema":
                target = (self.settings.llm_base_url or "", self.settings.llm_model or "")
                self._no_json_schema.add(target)
                log.info("провайдер не принял json_schema, переходим на json_object")
                return self._complete(client, messages, prompt, schema)
            self._record(prompt, messages, started, f"http_{exc.status_code}")
            raise LLMUnavailable(
                f"{prompt.prompt_id}: провайдер вернул HTTP {exc.status_code}"
            ) from exc
        except openai.APIStatusError as exc:
            self._record(prompt, messages, started, f"http_{exc.status_code}")
            raise LLMUnavailable(
                f"{prompt.prompt_id}: провайдер вернул HTTP {exc.status_code}"
            ) from exc
        except openai.APIError as exc:
            self._record(prompt, messages, started, type(exc).__name__)
            raise LLMUnavailable(f"{prompt.prompt_id}: {type(exc).__name__}") from exc

        elapsed = int((time.perf_counter() - started) * 1000)
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        self.stats.add(
            requests=1,
            ms=elapsed,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )
        log.info("%s: ответ за %d мс", prompt.prompt_id, elapsed)
        self._record(prompt, messages, started, "ok", len(content))
        if not content:
            raise LLMBadOutput(f"{prompt.prompt_id}: пустой ответ модели")
        return content

    def _create(
        self, client: Any, messages: list[dict[str, str]], response_format: dict[str, Any]
    ) -> Any:
        return client.chat.completions.create(
            model=self.settings.llm_model,
            messages=messages,
            temperature=0,
            response_format=response_format,
        )

    def _record(
        self,
        prompt: RenderedPrompt,
        messages: list[dict[str, str]],
        started: float,
        status: str,
        response_chars: int = 0,
    ) -> None:
        self._log(
            prompt,
            status=status,
            cached=False,
            messages=messages,
            response_chars=response_chars,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
