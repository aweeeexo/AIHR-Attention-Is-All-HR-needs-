"""Лимит анализов для публичного стенда (D62).

Сайт открыт по ссылке, и каждый анализ своего резюме тратит запросы к LLM за счёт владельца
ключа. Лимит — скользящее окно в час: общий (`ANALYSIS_LIMIT_PER_HOUR`) и на один адрес
(`ANALYSIS_LIMIT_PER_IP_HOUR`); 0 — без лимита (по умолчанию, как у жюри при запуске по README).
Пакет из N резюме считается за N анализов. Пример из кейса не считается: он из кэша.

Адрес клиента — первый в `X-Forwarded-For` (его ставят туннель и nginx веб-интерфейса), иначе адрес
соединения. Подделанный заголовок обходит лимит на адрес, но не общий лимит.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from aihr.config import get_settings

WINDOW_S = 3600.0


class AnalysisLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._all: deque[float] = deque()
        self._by_ip: dict[str, deque[float]] = {}

    def reset(self) -> None:
        with self._lock:
            self._all.clear()
            self._by_ip.clear()

    @staticmethod
    def _trim(q: deque[float], now: float) -> None:
        while q and now - q[0] >= WINDOW_S:
            q.popleft()

    def charge(self, ip: str, n: int = 1, now: float | None = None) -> None:
        """Списывает n анализов или бросает 429 с понятным текстом; при отказе ничего не списано."""
        s = get_settings()
        total, per_ip = s.analysis_limit_per_hour, s.analysis_limit_per_ip_hour
        if not total and not per_ip:
            return
        now = time.monotonic() if now is None else now
        with self._lock:
            self._trim(self._all, now)
            mine = self._by_ip.setdefault(ip, deque())
            self._trim(mine, now)
            if per_ip and len(mine) + n > per_ip:
                raise HTTPException(429, _message(per_ip, mine, now, "с вашего адреса"))
            if total and len(self._all) + n > total:
                raise HTTPException(429, _message(total, self._all, now, "на стенде"))
            for _ in range(n):
                self._all.append(now)
                mine.append(now)


def _message(limit: int, q: deque[float], now: float, where: str) -> str:
    wait = max(1, round((WINDOW_S - (now - q[0])) / 60)) if q else 60
    return (
        f"Лимит демо-стенда: не больше {limit} анализов в час {where}. Повторите через {wait} мин. "
        "Пример из кейса работает без лимита."
    )


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


limiter = AnalysisLimiter()


def charge(request: Request, n: int = 1) -> None:
    limiter.charge(client_ip(request), n)
