"""Реестр открытых вакансий (D58).

Рекрутер один раз добавляет вакансии (файлом или ссылкой), дальше загружает только резюме и
получает рейтинг по всем открытым вакансиям — сценарий из ответа эксперта: «рекрутер загружает
одно резюме, система выбирает наиболее подходящую из открытых вакансий».

Хранение — папка `vacancies_dir` (том Docker): исходные файлы `<id><расширение>` и `index.json`.
Отдельной СУБД нет: меньше сервисов, которые могут не подняться у проверяющих. При первом запуске
(нет `index.json`) реестр заполняется вакансиями примера из `case_dir` (`VACANCIES_SEED=0` — нет).
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from aihr.config import Settings, get_settings
from aihr.contracts import DocKind, IngestFailure
from aihr.ingest import SUPPORTED_EXTENSIONS, load_document
from aihr.inputs import case_files

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
INDEX = "index.json"


class RegistryVacancy(BaseModel):
    id: str
    title: str
    filename: str
    source: Literal["file", "url", "example"]
    url: str | None = None
    added_at: str


class RegistryError(ValueError):
    """Вакансию нельзя добавить; текст — для рекрутера."""


def _dir(s: Settings) -> Path:
    return s.vacancies_dir


def _read_index(s: Settings) -> list[RegistryVacancy]:
    path = _dir(s) / INDEX
    if not path.exists():
        return []
    return [RegistryVacancy(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _write_index(s: Settings, items: list[RegistryVacancy]) -> None:
    path = _dir(s) / INDEX
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    tmp.replace(path)


def _title(data: bytes, filename: str) -> str:
    """Проверяет файл тем же ingest, что и прогон; название — первая строка текста."""
    try:
        doc = load_document(data, filename, DocKind.vacancy, "V1")
    except IngestFailure as exc:
        raise RegistryError(exc.error.message) from exc
    first = next((f.text for f in sorted(doc.fragments, key=lambda f: f.order) if f.text), "")
    return first.strip().split("\n")[0][:120] or Path(filename).stem


def _ensure(s: Settings) -> None:
    d = _dir(s)
    if (d / INDEX).exists():
        return
    d.mkdir(parents=True, exist_ok=True)
    items: list[RegistryVacancy] = []
    if s.vacancies_seed:
        _, examples = case_files(s.case_dir)
        for path in examples:
            try:
                items.append(_store(s, path.read_bytes(), path.name, "example"))
            except RegistryError as exc:
                log.warning("пример не добавлен в реестр: %s", exc)
    _write_index(s, items)
    log.info("реестр вакансий создан: %d из примера", len(items))


def _store(
    s: Settings,
    data: bytes,
    filename: str,
    source: Literal["file", "url", "example"],
    url: str | None = None,
) -> RegistryVacancy:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise RegistryError("Поддерживаются DOCX, PDF, RTF и TXT.")
    title = _title(data, filename)
    item = RegistryVacancy(
        id=secrets.token_hex(6),
        title=title,
        filename=filename,
        source=source,
        url=url,
        added_at=datetime.now().isoformat(timespec="seconds"),
    )
    (_dir(s) / f"{item.id}{ext}").write_bytes(data)
    return item


def list_vacancies(settings: Settings | None = None) -> list[RegistryVacancy]:
    s = settings or get_settings()
    with _LOCK:
        _ensure(s)
        return _read_index(s)


def add_vacancy(
    data: bytes,
    filename: str,
    source: Literal["file", "url"] = "file",
    url: str | None = None,
    settings: Settings | None = None,
) -> RegistryVacancy:
    s = settings or get_settings()
    with _LOCK:
        _ensure(s)
        items = _read_index(s)
        if url and any(i.url == url for i in items):
            raise RegistryError("Эта ссылка уже есть в реестре.")
        item = _store(s, data, filename, source, url)
        _write_index(s, [*items, item])
        return item


def remove_vacancy(vacancy_id: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    with _LOCK:
        _ensure(s)
        items = _read_index(s)
        keep = [i for i in items if i.id != vacancy_id]
        if len(keep) == len(items):
            return False
        for path in _dir(s).glob(f"{vacancy_id}.*"):
            path.unlink(missing_ok=True)
        _write_index(s, keep)
        return True


def registry_files(settings: Settings | None = None) -> list[tuple[bytes, str]]:
    """Файлы реестра для прогона: (байты, исходное имя) в порядке добавления."""
    s = settings or get_settings()
    with _LOCK:
        _ensure(s)
        out = []
        for item in _read_index(s):
            path = _dir(s) / f"{item.id}{Path(item.filename).suffix.lower()}"
            if path.exists():
                out.append((path.read_bytes(), item.filename))
        return out
