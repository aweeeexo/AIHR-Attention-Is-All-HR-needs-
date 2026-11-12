"""Сбор входных файлов из путей и папок (CLI, пример из кейса).

В папке кейса резюме и вакансии лежат вместе. Когда папка передаётся как набор вакансий,
файлы с «резюме», «resume» или «cv» в имени пропускаются.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import Path

from aihr.ingest import SUPPORTED_EXTENSIONS

log = logging.getLogger(__name__)

_RESUME_NAME_RE = re.compile(r"резюме|resume|(?<![a-z])cv(?![a-z])", re.IGNORECASE)
_DIGITS_RE = re.compile(r"(\d+)")


def natural_key(path: Path) -> list[object]:
    """«Вакансия 2» раньше «Вакансия 10»."""
    return [int(p) if p.isdigit() else p.lower() for p in _DIGITS_RE.split(path.name)]


def looks_like_resume(path: Path) -> bool:
    return bool(_RESUME_NAME_RE.search(path.stem))


def _supported_files(directory: Path) -> list[Path]:
    files = [
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=natural_key)


def collect_vacancies(paths: Iterable[Path], exclude: Path | None = None) -> list[Path]:
    """Файлы берутся как есть, из папок — поддерживаемые файлы, кроме похожих на резюме."""
    excluded = exclude.resolve() if exclude else None
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            for f in _supported_files(path):
                if f.resolve() == excluded:
                    continue
                if looks_like_resume(f):
                    log.info("пропущен как резюме: %s", f.name)
                    continue
                out.append(f)
        else:
            out.append(path)
    return out


def case_files(case_dir: Path) -> tuple[list[Path], list[Path]]:
    """(резюме, вакансии) из папки с примером."""
    files = _supported_files(case_dir) if case_dir.is_dir() else []
    resumes = [f for f in files if looks_like_resume(f)]
    vacancies = [f for f in files if not looks_like_resume(f)]
    return resumes, vacancies


def read_files(paths: Iterable[Path]) -> list[tuple[bytes, str]]:
    return [(p.read_bytes(), p.name) for p in paths]
