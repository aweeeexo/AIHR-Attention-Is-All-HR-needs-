"""Извлечение: требования вакансии (T04) и профиль кандидата (T05-A)."""

from aihr.extract.profile import extract_profile
from aihr.extract.requirements import extract_requirements

__all__ = ["extract_profile", "extract_requirements"]
