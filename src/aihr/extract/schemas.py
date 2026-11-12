"""Схемы ответа модели для извлечения. Id, vacancy_id и нормализацию ставит код, не модель."""

from __future__ import annotations

from pydantic import BaseModel, Field

from aihr.contracts import Modality, ReqKind, ThresholdKind


class ExtractedThreshold(BaseModel):
    kind: ThresholdKind
    value: str | float = Field(description="«3» (лет), «higher» (образование), «B2» (язык)")
    subject: str | None = Field(default=None, description="к чему относится порог, если указано")


class ExtractedRequirement(BaseModel):
    text: str = Field(description="атомарная формулировка: одно проверяемое требование")
    kind: ReqKind
    modality_reason: str = Field(description="коротко: почему обязательное или желательное")
    modality: Modality
    alternatives: list[str] = Field(
        default_factory=list, description="варианты «A или B» — требование выполнено при любом"
    )
    threshold: ExtractedThreshold | None = None
    verifiable: bool = Field(default=True, description="можно ли проверить по тексту резюме")
    source_fragment_ids: list[str] = Field(
        min_length=1, description="номера фрагментов вакансии, где написано требование"
    )


class ExtractedRequirements(BaseModel):
    items: list[ExtractedRequirement]
