"""Синонимы (D14, T06). T00 — заглушка без словаря."""

from __future__ import annotations


def canonicalize(term: str) -> str | None:
    return None


def aliases(canonical: str) -> list[str]:
    return []
