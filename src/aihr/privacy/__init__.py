"""Маскирование ПДн. T00 — заглушка: masked_text = text, таблица замен пустая.

ВНИМАНИЕ: пока не готов T02, резюме кейса в LLM не отправляем (CLAUDE.md, «Работа с LLM»).
Пайплайн T00 к LLM не обращается.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aihr.contracts import Document


@dataclass
class PrivacyContext:
    """Таблица замен на один прогон, только в памяти. Ключ — метка, значение — исходный текст."""

    replacements: dict[str, str] = field(default_factory=dict)


def mask_document(doc: Document, ctx: PrivacyContext) -> Document:
    fragments = [f.model_copy(update={"masked_text": f.text}) for f in doc.fragments]
    return doc.model_copy(update={"fragments": fragments})


def unmask(text: str, ctx: PrivacyContext) -> str:
    for label, original in ctx.replacements.items():
        text = text.replace(label, original)
    return text
