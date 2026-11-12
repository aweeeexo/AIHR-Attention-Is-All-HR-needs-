"""Провайдер `replay` (D39): API модели, имитируемый через файлы.

Нужен, пока нет стабильного доступа к API. Клиент кладёт запрос — те же сообщения, что ушли бы
провайдеру, уже после guard — в `<LLM_REPLAY_DIR>/queue/<key>.json` и ждёт ответ в
`answers/<key>.json` (сырой текст ответа модели). Отвечает внешний исполнитель: человек или
модель вне процесса. Ответ дальше проходит обычный путь: разбор JSON, схема, повтор, кэш.

Ключ — хэш модели и сообщений: тот же запрос в следующем прогоне сразу находит готовый ответ.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aihr.contracts import LLMUnavailable

log = logging.getLogger(__name__)

POLL_S = 0.5


def request_key(model: str, messages: list[dict[str, str]]) -> str:
    payload = json.dumps({"model": model, "messages": messages}, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


class ReplayClient:
    """Объект с интерфейсом `openai.OpenAI().chat.completions.create(...)`."""

    def __init__(self, root: Path, wait_s: float, poll_s: float = POLL_S) -> None:
        self.root = root
        self.wait_s = wait_s
        self.poll_s = poll_s
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, *, model: str, messages: list[dict[str, str]], **_: Any) -> Any:
        key = request_key(model, messages)
        answer = self.root / "answers" / f"{key}.json"
        queued = self.root / "queue" / f"{key}.json"
        if not answer.is_file():
            _write_atomic(
                queued,
                json.dumps(
                    {"key": key, "model": model, "answer_path": str(answer), "messages": messages},
                    ensure_ascii=False,
                    indent=1,
                ),
            )
            log.info("replay: запрос %s в очереди", key)
            deadline = time.monotonic() + self.wait_s
            while not answer.is_file():
                if time.monotonic() >= deadline:
                    raise LLMUnavailable(f"replay: нет ответа на запрос {key}")
                time.sleep(self.poll_s)
            time.sleep(self.poll_s)  # исполнитель мог ещё дописывать файл
        content = answer.read_text(encoding="utf-8")
        queued.unlink(missing_ok=True)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None
        )
