"""Контракты v1: структуры данных и исключения на границах модулей.

Единственный источник правды. Текст дублируется в docs/contracts.md —
меняем оба в одном коммите и увеличиваем CONTRACTS_VERSION (D18).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

CONTRACTS_VERSION = 3


# ---------- 1. Вход ----------


class DocKind(StrEnum):
    resume = "resume"
    vacancy = "vacancy"


class FragmentSource(StrEnum):
    paragraph = "paragraph"
    list_item = "list_item"
    table_cell = "table_cell"
    header = "header"  # колонтитул
    footer = "footer"
    textbox = "textbox"
    pdf_line = "pdf_line"


class Fragment(BaseModel):
    id: str  # "R12" | "V2.7"
    order: int  # порядок в документе
    section: str | None  # заголовок раздела, найденный при разборе: "Опыт работы", "Требования"
    # нормализованная роль раздела: experience, education, skills, requirements,
    # duties, nice_to_have, conditions, about, contacts, other
    section_role: str | None
    source: FragmentSource
    text: str  # исходный текст. НИКОГДА не уходит наружу
    masked_text: str = ""  # текст после маскирования ПДн. Только он уходит во внешний API


class IngestErrorCode(StrEnum):
    empty_file = "E_EMPTY_FILE"
    too_large = "E_TOO_LARGE"
    unsupported_type = "E_UNSUPPORTED_TYPE"
    type_mismatch = "E_TYPE_MISMATCH"  # расширение не совпадает с содержимым
    corrupted = "E_CORRUPTED"
    encrypted = "E_ENCRYPTED"
    no_text = "E_NO_TEXT"  # скан без текстового слоя
    no_requirements = "E_NO_REQUIREMENTS"  # из вакансии не извлечено ни одного требования


class IngestError(BaseModel):
    code: IngestErrorCode
    filename: str
    message: str  # для пользователя, по-русски
    hint: str  # что сделать: «пересохраните в docx» и т. п.


class Document(BaseModel):
    id: str  # "R" | "V2"
    content_hash: str
    kind: DocKind
    filename: str
    title: str | None = None  # для вакансии — название должности, если найдено
    fragments: list[Fragment]
    warnings: list[str] = []  # «похоже не на резюме», «документ обрезан до 200 страниц» и т. п.


# ---------- 2. Извлечение: вакансия ----------


class ReqKind(StrEnum):
    skill = "skill"  # инструмент, технология, предметное знание
    experience = "experience"  # опыт работы в роли / области, часто с порогом лет
    education = "education"
    language = "language"
    certificate = "certificate"
    soft = "soft"  # личные качества, обычно не проверяются по резюме
    duty = "duty"  # обязанность из вакансии → всегда modality=nice (D3)
    other = "other"


class Modality(StrEnum):
    must = "must"
    nice = "nice"


class ThresholdKind(StrEnum):
    years = "years"  # «опыт от 3 лет»
    education_level = "education_level"  # «высшее образование»
    language_level = "language_level"  # «английский не ниже B2»


class Threshold(BaseModel):
    kind: ThresholdKind
    value: str  # "3" | "higher" | "B2" — нормализованное значение
    subject: str | None = None  # к чему относится: «управление проектами», «английский»


class Requirement(BaseModel):
    id: str  # "V2.req3"
    vacancy_id: str  # "V2"
    text: str  # атомарная формулировка
    kind: ReqKind
    modality: Modality
    # найденный маркер: «обязательно», «будет плюсом». None → правило по умолчанию
    modality_marker: str | None
    modality_reason: str  # коротко, почему must / nice
    alternatives: list[str] = []  # «A или B» — одно требование с альтернативами
    threshold: Threshold | None = None
    canonical_terms: list[str] = []  # канонические термины после слоя синонимов
    verifiable: bool = True  # можно ли проверить по резюме (soft-skills часто нельзя)
    source_fragment_ids: list[str] = Field(min_length=1)


# ---------- 2. Извлечение: резюме ----------


class YearMonth(BaseModel):
    year: int
    month: int | None = None  # None → известен только год


class TaskLevel(StrEnum):
    executor = "executor"  # исполнял, помогал
    independent = "independent"  # вёл самостоятельно
    lead = "lead"  # руководил людьми или направлением


class Position(BaseModel):
    title: str
    organization: str | None
    start: YearMonth | None  # заполняет код из raw_dates (normalize/dates.py)
    end: YearMonth | None
    is_current: bool = False
    raw_dates: str | None  # как написано в резюме
    duration_months: int | None = None  # считает код
    dates_approximate: bool = False  # известен только год
    tasks: list[str] = []
    achievements: list[str] = []
    tools: list[str] = []
    level: TaskLevel | None = None
    scale: str | None = None  # «команда 5 чел.», «бюджет 10 млн ₽» — только если прямо написано
    fragment_ids: list[str] = Field(min_length=1)


class EducationLevel(StrEnum):
    secondary = "secondary"
    vocational = "vocational"  # среднее специальное
    incomplete_higher = "incomplete_higher"
    bachelor = "bachelor"
    specialist = "specialist"
    master = "master"
    phd = "phd"  # кандидат наук
    doctor = "doctor"  # доктор наук
    course = "course"  # курсы, не уровень образования


class Education(BaseModel):
    level: EducationLevel | None
    institution: str | None
    field: str | None
    year_end: int | None
    fragment_ids: list[str] = Field(min_length=1)


class MentionType(StrEnum):
    listed_only = "listed_only"  # только в списке навыков
    evidenced = "evidenced"  # подтверждён описанием опыта


class SkillMention(BaseModel):
    name: str
    canonical: str | None = None
    mention_type: MentionType
    years: float | None = None  # считает код: объединение периодов мест работы, где навык упомянут
    last_used_year: int | None = None  # считает код
    fragment_ids: list[str] = Field(min_length=1)


class Language(BaseModel):
    name: str
    level_raw: str | None
    cefr: str | None = None  # A1..C2, нормализует код (normalize/levels.py)
    fragment_ids: list[str] = Field(min_length=1)


class Fact(BaseModel):
    text: str  # сертификат, публикация, награда, прочее
    category: str
    fragment_ids: list[str] = Field(min_length=1)


class CandidateProfile(BaseModel):
    positions: list[Position] = []
    education: list[Education] = []
    skills: list[SkillMention] = []
    languages: list[Language] = []
    certificates: list[Fact] = []
    other: list[Fact] = []
    total_experience_months: int | None = None  # считает код, объединение периодов
    gaps_months: list[tuple[YearMonth, YearMonth]] = []  # перерывы > 6 мес, считает код


# ---------- 3. Сопоставление ----------


class Status(StrEnum):
    match = "match"  # Соответствует
    partial = "partial"  # Частично
    mismatch = "mismatch"  # Не соответствует
    not_stated = "not_stated"  # Не указано


STATUS_RU = {
    Status.match: "Соответствует",
    Status.partial: "Частично",
    Status.mismatch: "Не соответствует",
    Status.not_stated: "Не указано",
}


class EvidenceType(StrEnum):
    direct = "direct"  # прямо написано
    indirect = "indirect"  # следует из другого факта: цепочка вывода обязательна
    adjacent = "adjacent"  # смежный навык того же класса → максимум partial


class Evidence(BaseModel):
    fragment_id: str
    quote: str  # ЗАПОЛНЯЕТ КОД из Fragment.text, не модель


class Verdict(BaseModel):
    requirement_id: str
    status: Status
    evidence_type: EvidenceType | None = None
    evidence: list[Evidence] = []
    inference: str | None = None  # для indirect: «[R7] PostgreSQL 3 года → владеет SQL»
    missing: str | None = None  # для partial: чего не хватает
    comment: str  # для рекрутера, ≤ 250 символов, без фактов вне evidence
    confidence: float = Field(ge=0, le=1)
    computed: str | None = None  # расчёт правила: «03.2021–06.2024 = 3 г. 3 мес. ≥ 3 лет»
    partial_value: float | None = None  # доля для partial, если есть порог: 1.5 / 3 = 0.5
    decided_by: Literal["pass_a", "pass_b", "rule", "fallback"]
    needs_review: bool = False  # проходы A и B не согласны, или must с косвенным доказательством


# ---------- 4. Балл и рейтинг ----------


class FitLabel(StrEnum):
    fits = "fits"  # подходит
    fits_with_caveats = "fits_with_caveats"  # подходит с оговорками
    not_fit = "not_fit"  # не подходит


class StatusCounts(BaseModel):
    total: int = 0
    match: int = 0
    partial: int = 0
    mismatch: int = 0
    not_stated: int = 0


class VacancyScore(BaseModel):
    vacancy_id: str
    title: str | None
    score: float  # 0..100, u = 0.5
    score_min: float  # u = 0
    score_max: float  # u = 1
    must: StatusCounts
    nice: StatusCounts
    blocking_gaps: list[str]  # requirement_id обязательных со статусом mismatch (D4)
    label: FitLabel
    top_plus: list[str]  # requirement_id с наибольшим вкладом в балл
    top_minus: list[str]  # requirement_id с наибольшей потерей
    explanation: str  # собирается шаблоном из чисел, без LLM


class Ranking(BaseModel):
    items: list[VacancyScore]  # отсортированы по убыванию
    best_vacancy_id: str | None
    comparison: list[str]  # «V1 выше V3 на 31 пункт: ...» — шаблоном
    formula: str  # человекочитаемая формула и веса из конфига
    summary: str = ""  # итог рейтинга; «прямо не подходит ни одна» + косвенные варианты (D35, v2)


# ---------- 5. Отчёт ----------


class Point(BaseModel):
    text: str
    requirement_ids: list[str] = []
    fragment_ids: list[str] = []  # фрагменты резюме, на которые опирается пункт


class Question(BaseModel):
    requirement_id: str | None
    text: str
    kind: Literal["factual", "behavioral"]
    why: str  # «в резюме не указан уровень английского»


class RequirementRow(BaseModel):
    requirement_id: str
    requirement: str
    modality: Modality
    vacancy_quote: str  # из source_fragment_ids, подставляет код
    resume_evidence: list[Evidence]
    status: Status
    status_ru: str
    evidence_type: EvidenceType | None
    comment: str
    computed: str | None


class VerificationStats(BaseModel):
    quotes_total: int
    quotes_verified: int  # должно быть равно quotes_total
    generated_entities_total: int
    generated_entities_unverified: int  # должно быть 0


class Report(BaseModel):
    vacancy_id: str
    rows: list[RequirementRow]
    strengths: list[Point]
    gaps: list[Point]
    risks: list[Point]
    questions: list[Question]
    beyond_requirements: list[Point]  # позиция кандидата (D7), на балл не влияет
    recruiter_recommendation: str
    candidate_message: str
    verification: VerificationStats
    summary: str = ""  # вывод для нанимающего менеджера сверху отчёта (D36, v2)


# ---------- 6. Итог прогона ----------


class MatchResult(BaseModel):
    contracts_version: int = CONTRACTS_VERSION
    run_id: str
    mode: Literal["llm", "fallback"]
    resume: Document | None
    profile: CandidateProfile | None
    vacancies: list[Document]
    requirements: dict[str, list[Requirement]]  # vacancy_id → требования
    verdicts: dict[str, list[Verdict]]  # vacancy_id → вердикты
    ranking: Ranking | None
    reports: dict[str, Report]  # vacancy_id → отчёт
    errors: list[IngestError] = []
    warnings: list[str] = []
    outbound_log_path: str | None = None
    timings_ms: dict[str, int] = {}


# ---------- 6а. Пакет: несколько резюме × вакансии (D38, v3) ----------


class BatchResume(BaseModel):
    resume_id: str  # C1, C2, … — по порядку загрузки
    filename: str
    run_id: str | None = None  # полный MatchResult этого кандидата — GET /runs/{run_id}
    mode: Literal["llm", "fallback"] | None = None
    best_vacancy_id: str | None = None
    error: IngestError | None = None  # резюме не прочиталось — кандидат в матрицу не попал


class BatchCell(BaseModel):
    resume_id: str
    vacancy_id: str
    score: float
    score_min: float
    score_max: float
    label: FitLabel
    must_match: int
    must_total: int


class BatchVacancy(BaseModel):
    vacancy_id: str  # V1, V2, … — одинаковые во всех прогонах пакета
    filename: str
    title: str | None = None
    candidates: list[str] = []  # resume_id: лучшие первыми, порядок считает код (D11)
    summary: str = ""


class BatchResult(BaseModel):
    contracts_version: int = CONTRACTS_VERSION
    batch_id: str
    resumes: list[BatchResume]
    vacancies: list[BatchVacancy]
    cells: list[BatchCell]
    errors: list[IngestError] = []  # ошибки вакансий — один раз на пакет
    warnings: list[str] = []
    summary: str = ""


# ---------- 7. Исключения на границах модулей ----------


class IngestFailure(Exception):
    """Документ не загружен. Несёт IngestError, который пайплайн кладёт в MatchResult.errors."""

    def __init__(self, error: IngestError) -> None:
        super().__init__(f"{error.code.value}: {error.message}")
        self.error = error


class LLMUnavailable(Exception):
    """Сеть, таймауты, 5xx после всех повторов или LLM_PROVIDER=none."""


class LLMBadOutput(Exception):
    """Ответ модели не прошёл схему после всех повторов."""


class PrivacyViolation(Exception):
    """Guard нашёл ПДн в исходящем тексте. Сам найденный фрагмент в сообщение не кладём."""
