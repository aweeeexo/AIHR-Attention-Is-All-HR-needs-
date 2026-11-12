"""Guard: последняя проверка исходящего текста перед отправкой в LLM (T02, шаг 4).

Нашли email, телефон, ссылку, документ или ФИО кандидата — запрос не уходит, бросается
PrivacyViolation. В сообщении — что именно найдено и в каком промпте, но не сами данные.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aihr.contracts import PrivacyViolation
from aihr.privacy.patterns import GUARD_PATTERNS

if TYPE_CHECKING:
    from aihr.privacy import PrivacyContext


def check_outbound(text: str, ctx: PrivacyContext | None, prompt_id: str) -> None:
    for name, pattern in GUARD_PATTERNS.items():
        if pattern.search(text):
            raise PrivacyViolation(f"guard: найден {name} в промпте {prompt_id}")
    if ctx is None:
        return
    for pattern in ctx.name_patterns:
        if pattern.search(text):
            raise PrivacyViolation(f"guard: найдено ФИО кандидата в промпте {prompt_id}")
    lowered = text.lower()
    for value in ctx.guarded_values():
        if value.lower() in lowered:
            raise PrivacyViolation(f"guard: найдено исходное значение ПДн в промпте {prompt_id}")
