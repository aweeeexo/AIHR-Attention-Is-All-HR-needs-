"""Схемы ответа модели для извлечения. Id, vacancy_id и нормализацию ставит код, не модель."""

from __future__ import annotations

from pydantic import BaseModel, Field

from aihr.contracts import EducationLevel, Modality, ReqKind, TaskLevel, ThresholdKind


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


# ---------- профиль кандидата (T05-A) ----------


class ExtractedPosition(BaseModel):
    title: str = Field(description="должность как написана")
    organization: str | None = None
    raw_dates: str | None = Field(
        default=None, description="даты работы дословно из резюме, без пересчёта"
    )
    tasks: list[str] = Field(default_factory=list, description="что делал, коротко")
    achievements: list[str] = Field(default_factory=list, description="результаты с цифрами")
    tools: list[str] = Field(default_factory=list, description="инструменты, технологии")
    level_reason: str = Field(default="", description="почему выбран уровень задач")
    level: TaskLevel | None = None
    scale: str | None = Field(default=None, description="масштаб, только если прямо написан")
    fragment_ids: list[str] = Field(min_length=1)


class ExtractedEducation(BaseModel):
    level: EducationLevel | None = None
    institution: str | None = None
    field: str | None = None
    year_end: int | None = None
    fragment_ids: list[str] = Field(min_length=1)


class ExtractedSkill(BaseModel):
    name: str
    fragment_ids: list[str] = Field(min_length=1, description="все фрагменты, где навык упомянут")


class ExtractedLanguage(BaseModel):
    name: str
    level_raw: str | None = Field(default=None, description="уровень как написан")
    fragment_ids: list[str] = Field(min_length=1)


class ExtractedFact(BaseModel):
    text: str
    category: str = Field(
        description="certificate, course, publication, award, volunteering, other"
    )
    fragment_ids: list[str] = Field(min_length=1)


class ExtractedProfile(BaseModel):
    positions: list[ExtractedPosition] = Field(default_factory=list)
    education: list[ExtractedEducation] = Field(default_factory=list)
    skills: list[ExtractedSkill] = Field(default_factory=list)
    languages: list[ExtractedLanguage] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
