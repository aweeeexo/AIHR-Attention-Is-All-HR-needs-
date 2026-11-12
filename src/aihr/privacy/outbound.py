"""Журнал исходящих запросов: data/runs/<run_id>/outbound.jsonl, одна строка на запрос.

Текст запроса пишем целиком: он уже прошёл маскирование и guard. Заблокированный guard'ом запрос
пишем без текста — только причину.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class OutboundLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, **entry: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), **entry}
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
