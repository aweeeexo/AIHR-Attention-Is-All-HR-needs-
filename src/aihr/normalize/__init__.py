"""Нормализация: даты, стаж, уровни (T05), синонимы (T06)."""

from aihr.normalize.synonyms import aliases, canonicalize
from aihr.normalize.tenure import enrich_profile

__all__ = ["aliases", "canonicalize", "enrich_profile"]
