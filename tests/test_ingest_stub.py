"""Минимальная загрузка T00: форматы, id фрагментов, базовые коды ошибок. Полный набор — T01."""

import pytest

from aihr.contracts import DocKind, FragmentSource, IngestErrorCode, IngestFailure
from aihr.ingest import load_document
from tests.conftest import fixture_file, make_docx


def test_txt_resume_fragments() -> None:
    data, name = fixture_file("resume_cook.txt")
    doc = load_document(data, name, DocKind.resume, "R")
    assert doc.id == "R" and doc.kind == DocKind.resume
    assert [f.id for f in doc.fragments[:3]] == ["R1", "R2", "R3"]
    assert [f.order for f in doc.fragments] == list(range(1, len(doc.fragments) + 1))
    assert len(doc.content_hash) == 12
    assert doc.title is None


def test_docx_vacancy_with_table() -> None:
    data = make_docx(["Сварщик", "", "Требования:"], table=[["Опыт", "от 2 лет"]])
    doc = load_document(data, "Вакансия 7.docx", DocKind.vacancy, "V2")
    assert [f.id for f in doc.fragments] == ["V2.1", "V2.2", "V2.3", "V2.4"]
    assert doc.title == "Сварщик"
    assert doc.fragments[-1].source == FragmentSource.table_cell
    assert doc.fragments[-1].text == "от 2 лет"


def test_cp1251_txt() -> None:
    text = "Требования:\nОпыт работы поваром от 3 лет, санитарная книжка обязательна."
    doc = load_document(text.encode("cp1251"), "v.txt", DocKind.vacancy, "V1")
    assert doc.fragments[1].text.startswith("Опыт работы поваром")


def test_same_text_same_hash() -> None:
    a = load_document("Повар\nОпыт".encode(), "a.txt", DocKind.vacancy, "V1")
    b = load_document("Повар  \n\n Опыт".encode(), "b.txt", DocKind.vacancy, "V2")
    assert a.content_hash == b.content_hash


@pytest.mark.parametrize(
    ("data", "name", "code"),
    [
        (b"", "empty.docx", IngestErrorCode.empty_file),
        (b"MZ\x90\x00", "virus.exe", IngestErrorCode.unsupported_type),
        (b"PK\x03\x04broken", "broken.docx", IngestErrorCode.corrupted),
        (b"%PDF-1.4 broken", "broken.pdf", IngestErrorCode.corrupted),
        (b"   \n\n\t ", "blank.txt", IngestErrorCode.no_text),
    ],
)
def test_error_codes(data: bytes, name: str, code: IngestErrorCode) -> None:
    with pytest.raises(IngestFailure) as exc:
        load_document(data, name, DocKind.vacancy, "V1")
    err = exc.value.error
    assert err.code == code
    assert err.filename == name
    assert err.message and err.hint


def test_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    from aihr.config import get_settings

    monkeypatch.setenv("MAX_FILE_MB", "0.001")
    get_settings.cache_clear()
    with pytest.raises(IngestFailure) as exc:
        load_document(b"x" * 2000, "big.txt", DocKind.resume, "R")
    assert exc.value.error.code == IngestErrorCode.too_large
