"""Схема ответа модели в проходе A (T07). Цитаты модель не пишет — только номера фрагментов."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from aihr.contracts import EvidenceType, Status


class PassAVerdict(BaseModel):
    requirement_id: str
    reasoning: str = Field(description="коротко: что есть в резюме по теме и почему такой статус")
    status: Status
    evidence_type: EvidenceType | None = None
    # Обязательное поле: без него часть моделей молча пропускает номера, и вывод теряется
    fragment_ids: list[str] = Field(
        description="номера фрагментов резюме, подтверждающих вывод; для not_stated — []"
    )
    inference: str | None = Field(
        default=None, description="для indirect: цепочка вывода со ссылками [R12] на фрагменты"
    )
    missing: str | None = Field(default=None, description="для partial: чего не хватает")
    comment: str = Field(description="для рекрутера, до 250 символов, только по фрагментам")
    confidence: float = Field(default=0.7, ge=0, le=1)

    @model_validator(mode="after")
    def _evidence_for_conclusion(self) -> PassAVerdict:
        # Ошибка уходит модели в повторном запросе (client.py): она дописывает номера сама
        if self.status != Status.not_stated and not self.fragment_ids:
            raise ValueError(
                f"{self.requirement_id}: для статуса {self.status.value} укажи fragment_ids — "
                "номера фрагментов резюме; если подтверждения нет, ставь not_stated"
            )
        return self


class PassAResult(BaseModel):
    verdicts: list[PassAVerdict]
