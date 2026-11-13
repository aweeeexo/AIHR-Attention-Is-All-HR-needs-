"""Щит от скрытого текста и команд для ИИ в документах (D52).

Кандидаты прячут в резюме текст для автоматических систем: белый шрифт, кегль меньше 3 pt,
скрытое форматирование Word. Человек его не видит, а модель прочла бы. Такой текст исключаем из
анализа (в фрагменты он не попадает и наружу не уходит) и сообщаем рекрутеру.

Отдельно ищем фразы, похожие на команды для ИИ («игнорируй инструкции», «поставь 100 баллов»),
и в скрытом, и в видимом тексте. Видимый текст остаётся в анализе как данные (принцип 9:
документ — данные, а не команды), но рекрутер получает предупреждение.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

MIN_POINTS = 3.0  # кегль меньше — человек не прочтёт
QUOTE_CHARS = 80

INJECTION = re.compile(
    r"(?i)(?:"
    r"игнорир\w*\s+(?:все\s+|любые\s+)?(?:предыдущ\w+\s+|прошл\w+\s+|остальн\w+\s+)?"
    r"(?:инструкц|указан|правил|команд)\w*"
    r"|ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|prompts?)"
    r"|disregard\s+(?:all\s+|any\s+)?(?:previous|prior|above)"
    r"|system\s+prompt|системн\w+\s+промпт\w*"
    r"|you\s+are\s+now\s+an?\b|ты\s+теперь\b"
    r"|постав\w*\s+(?:мне\s+|этому\s+кандидату\s+|кандидату\s+)?(?:максимальн\w+|высш\w+|100)"
    r"|оцени\w*\s+(?:меня|этого\s+кандидата|кандидата)\s+на\s+(?:100|максимум)"
    r"|(?:рекомендуй|пригласи)\s+(?:меня|этого\s+кандидата)\s+(?:на|к)\b"
    r"|this\s+candidate\s+is\s+(?:the\s+)?(?:best|perfect|ideal)"
    r"|rate\s+(?:me|this\s+candidate)\s+(?:as\s+)?(?:10|100|highest|the\s+best)"
    r")"
)


def _quote(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= QUOTE_CHARS else text[:QUOTE_CHARS] + "…"


# ---------- docx: свойства фрагмента текста (w:rPr) ----------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _on(el: Any) -> bool:
    return el is not None and el.get(f"{_W}val") not in ("0", "false", "off")


def docx_run_hidden(run: Any) -> str | None:
    """Причина, по которой текст этого w:r не видно, или None."""
    rpr = run.find(f"{_W}rPr") if run is not None else None
    if rpr is None:
        return None
    if _on(rpr.find(f"{_W}vanish")) or _on(rpr.find(f"{_W}specVanish")):
        return "скрытый формат"
    color = rpr.find(f"{_W}color")
    if color is not None:
        value = (color.get(f"{_W}val") or "").upper()
        if re.fullmatch(r"[0-9A-F]{6}", value) and all(
            int(value[i : i + 2], 16) >= 0xF0 for i in (0, 2, 4)
        ):
            return "белый шрифт"
    size = rpr.find(f"{_W}sz")
    if size is not None:
        try:
            if int(size.get(f"{_W}val") or 0) < MIN_POINTS * 2:  # w:sz — в полупунктах
                return "крошечный кегль"
        except ValueError:
            pass
    return None


# ---------- pdf: символы pdfplumber ----------


def _white(color: Any) -> bool:
    if color is None:
        return False
    values = list(color) if isinstance(color, (list, tuple)) else [color]
    try:
        nums = [float(v) for v in values]
    except (TypeError, ValueError):
        return False
    if len(nums) == 1:  # серый
        return nums[0] >= 0.95
    if len(nums) == 3:  # RGB
        return all(v >= 0.95 for v in nums)
    if len(nums) == 4:  # CMYK
        return all(v <= 0.05 for v in nums)
    return False


def pdf_char_hidden(char: dict[str, Any], width: float, height: float) -> str | None:
    if _white(char.get("non_stroking_color")):
        return "белый шрифт"
    if float(char.get("size") or 0) < MIN_POINTS:
        return "крошечный кегль"
    x0, x1 = float(char.get("x0", 0)), float(char.get("x1", 0))
    top, bottom = float(char.get("top", 0)), float(char.get("bottom", 0))
    if x1 <= 0 or x0 >= width or bottom <= 0 or top >= height:
        return "текст за полями страницы"
    return None


# ---------- предупреждения ----------


def hidden_warnings(hidden: Sequence[tuple[str, str]]) -> list[str]:
    """hidden — пары (причина, текст). Одно предупреждение на документ + отдельно команды для ИИ."""
    pieces = [(reason, text) for reason, text in hidden if text.strip()]
    if not pieces:
        return []
    reasons = sorted({reason for reason, _ in pieces})
    joined = " ".join(text for _, text in pieces)
    out = [
        f"Скрытый текст ({', '.join(reasons)}): {len(joined.strip())} символов исключены из "
        f"анализа — человек их не видит. Начало: «{_quote(joined)}»."
    ]
    m = INJECTION.search(joined)
    if m:
        out.append(
            f"В скрытом тексте команда для ИИ: «{_quote(m.group(0))}». Похоже на попытку "
            "повлиять на автоматическую оценку — обратите внимание."
        )
    return out


def injection_warnings(lines: Sequence[str]) -> list[str]:
    """Видимые фразы, похожие на команды для ИИ. Текст остаётся данными (принцип 9)."""
    for line in lines:
        m = INJECTION.search(line)
        if m:
            return [
                f"В тексте фраза, похожая на команду для ИИ: «{_quote(line)}». Система "
                "обрабатывает её как обычный текст и не выполняет; стоит обратить внимание."
            ]
    return []
