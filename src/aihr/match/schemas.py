"""Схема ответа модели в проходе A (T07). Цитаты модель не пишет — только номера фрагментов."""

from __future__ import annotations

from pydantic import BaseModel, Field

from aihr.contracts import EvidenceType, Status


class PassAVerdict(BaseModel):
    requirement_id: str
    reasoning: str = Field(description="коротко: что есть в резюме по теме и почему такой статус")
    status: Status
    evidence_type: EvidenceType | None = None
    fragment_ids: list[str] = Field(
        default_factory=list, description="номера фрагментов резюме, подтверждающих вывод"
    )
    inference: str | None = Field(
        default=None, description="для indirect: цепочка вывода со ссылками [R12] на фрагменты"
    )
    missing: str | None = Field(default=None, description="для partial: чего не хватает")
    comment: str = Field(description="для рекрутера, до 250 символов, только по фрагментам")
    confidence: float = Field(default=0.7, ge=0, le=1)


class PassAResult(BaseModel):
    verdicts: list[PassAVerdict]
