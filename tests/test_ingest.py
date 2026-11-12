"""T01: лестница проверок, форматы, нормализация, разделы, эталон по документам кейса."""

import io
from collections import Counter

import pytest

from aihr.config import get_settings
from aihr.contracts import DocKind, Document, FragmentSource, IngestErrorCode, IngestFailure
from aihr.ingest import fix_filename, load_document
from aihr.ingest.sections import match_heading
from aihr.ingest.text import join_wrapped_lines, normalize, split_long, strip_bullet
from tests.bad_files import BAD_FILES, BadFile
from tests.conftest import CASE_DIR, FIXTURES

NBSP, SHY, ZWSP, BOM = chr(0xA0), chr(0xAD), chr(0x200B), chr(0xFEFF)


def _doc_id(kind: DocKind) -> str:
    return "R" if kind == DocKind.resume else "V1"


# ---------- плохие и нестандартные файлы ----------


@pytest.mark.parametrize("bf", BAD_FILES, ids=lambda b: b.name)
def test_bad_files(bf: BadFile) -> None:
    data = bf.make()
    if bf.code is not None:
        with pytest.raises(IngestFailure) as exc:
            load_document(data, bf.name, bf.kind, _doc_id(bf.kind))
        err = exc.value.error
        assert err.code == bf.code
        assert err.filename == bf.name
        assert err.message and err.hint
        assert "Traceback" not in err.message + err.hint
        return
    doc = load_document(data, bf.name, bf.kind, _doc_id(bf.kind))
    assert doc.fragments
    if bf.warning:
        assert any(bf.warning in w for w in doc.warnings), doc.warnings


def test_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_FILE_MB", "0.001")
    get_settings.cache_clear()
    with pytest.raises(IngestFailure) as exc:
        load_document(b"x" * 2000, "big.txt", DocKind.resume, "R")
    assert exc.value.error.code == IngestErrorCode.too_large


def _load(name: str, kind: DocKind = DocKind.resume) -> Document:
    bf = next(b for b in BAD_FILES if b.name == name)
    return load_document(bf.make(), bf.name, kind, _doc_id(kind))


def test_encodings_decoded_same() -> None:
    names = ("resume_cp1251.txt", "resume_utf8_bom.txt", "resume_utf16.txt")
    texts = [[f.text for f in _load(n).fragments] for n in names]
    assert texts[0] == texts[1] == texts[2]
    assert texts[0][1] == "Опыт работы"
    assert not texts[0][0].startswith(BOM)


def test_header_and_textbox_are_read() -> None:
    doc = _load("resume_header_textbox.docx")
    sources = {f.source for f in doc.fragments}
    assert {FragmentSource.header, FragmentSource.textbox} <= sources
    assert doc.fragments[0].source == FragmentSource.header  # колонтитул идёт первым
    box = next(f for f in doc.fragments if f.source == FragmentSource.textbox)
    assert box.section_role == "skills"


def test_two_column_table_roles() -> None:
    doc = _load("resume_two_columns.docx")
    roles = {f.text: f.section_role for f in doc.fragments}
    assert roles["Опыт работы"] == "experience"
    assert roles["Образование"] == "education"
    assert all(f.source == FragmentSource.table_cell for f in doc.fragments)


def test_rtf_both_encodings() -> None:
    texts = [f.text for f in _load("resume.rtf").fragments]
    assert texts[0] == "Опыт работы"
    assert texts[2] == "Образование"
    assert "юрист в юридической фирме" in texts[1]


def test_merged_cells_not_duplicated() -> None:
    import docx

    d = docx.Document()
    t = d.add_table(rows=2, cols=3)
    t.cell(0, 0).merge(t.cell(0, 2)).text = "Опыт работы"
    t.cell(1, 0).text = "2019 — 2024, ООО «Пример», инженер-сметчик, составлял сметы."
    buf = io.BytesIO()
    d.save(buf)
    doc = load_document(buf.getvalue(), "r.docx", DocKind.resume, "R")
    assert [f.text for f in doc.fragments].count("Опыт работы") == 1


def test_list_items_and_bullets() -> None:
    text = "Требования:\n• опыт работы поваром от 3 лет;\n- санитарная книжка;\n1. Знание техкарт."
    doc = load_document(text.encode(), "v.txt", DocKind.vacancy, "V2")
    items = doc.fragments[1:]
    assert [f.text for f in items] == [
        "опыт работы поваром от 3 лет;",
        "санитарная книжка;",
        "Знание техкарт.",
    ]
    assert all(f.source == FragmentSource.list_item for f in items)
    assert all(f.section_role == "requirements" for f in items)
    assert [f.id for f in doc.fragments] == ["V2.1", "V2.2", "V2.3", "V2.4"]


def test_long_paragraph_split_and_ids() -> None:
    sentence = "Отвечал за планирование смен и контроль качества продукции на участке. "
    doc = load_document((sentence * 20).encode(), "r.txt", DocKind.resume, "R")
    assert len(doc.fragments) > 1
    assert all(len(f.text) <= 400 for f in doc.fragments)
    assert [f.order for f in doc.fragments] == list(range(1, len(doc.fragments) + 1))


def test_same_text_same_hash() -> None:
    body = "Опыт работы\n2019 — 2024 повар горячего цеха в ресторане «Север»."
    a = load_document(body.encode(), "a.txt", DocKind.resume, "R")
    other = ("  " + body.replace("\n", "\n\n")).encode("cp1251")
    b = load_document(other, "b.txt", DocKind.resume, "R")
    assert a.content_hash == b.content_hash
    assert len(a.content_hash) == 12


# ---------- текст ----------


def test_normalize() -> None:
    raw = f"  Опыт{NBSP}работы{SHY}  {ZWSP}5 лет "
    assert normalize(raw) == "Опыт работы 5 лет"


@pytest.mark.parametrize(
    ("raw", "text", "bullet"),
    [
        ("• Пункт", "Пункт", True),
        ("- пункт", "пункт", True),
        ("1) пункт", "пункт", True),
        ("2019 – 2023 повар", "2019 – 2023 повар", False),
        ("—", "—", False),
    ],
)
def test_strip_bullet(raw: str, text: str, bullet: bool) -> None:
    assert strip_bullet(raw) == (text, bullet)


def test_join_wrapped_lines() -> None:
    lines = ["Разрабатывал интер-", "фейсы для клиентов", "и сопровождал их.", "Навыки:", "SQL"]
    assert join_wrapped_lines(lines) == [
        "Разрабатывал интерфейсы для клиентов и сопровождал их.",
        "Навыки:",
        "SQL",
    ]


def test_split_long_keeps_short() -> None:
    assert split_long("коротко") == ["коротко"]


# ---------- заголовки ----------


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [
        ("Опыт работы", DocKind.resume, ("experience", False)),
        ("ОПЫТ РАБОТЫ:", DocKind.resume, ("experience", False)),
        ("Опыт работы — 6 лет 2 месяца", DocKind.resume, ("experience", False)),
        ("Опыт работы: 3 года", DocKind.resume, ("experience", False)),
        ("Навыки: Excel, SQL", DocKind.resume, ("skills", True)),
        ("Будет плюсом: опыт с пароконвектоматом", DocKind.vacancy, ("nice_to_have", True)),
        ("Чем предстоит заниматься:", DocKind.vacancy, ("duties", False)),
        ("Мы предлагаем", DocKind.vacancy, ("conditions", False)),
        ("Nice to have", DocKind.vacancy, ("nice_to_have", False)),
        ("1. Требования", DocKind.vacancy, ("requirements", False)),
    ],
)
def test_match_heading(text: str, kind: DocKind, expected: tuple[str, bool]) -> None:
    got = match_heading(text, kind)
    assert got is not None
    assert (got[0], got[2]) == expected


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Опыт работы поваром от 3 лет", DocKind.vacancy),  # требование, а не заголовок
        ("Образование: высшее экономическое.", DocKind.vacancy),  # строка требований
        ("Опыт работы с Python 3 года в банке", DocKind.resume),
    ],
)
def test_not_heading(text: str, kind: DocKind) -> None:
    assert match_heading(text, kind) is None


# ---------- вакансии других профессий ----------

OTHER = {
    "nurse.txt": (
        "Медицинская сестра процедурного кабинета",
        {"duties", "requirements", "conditions"},
    ),
    "sales.txt": (
        "Менеджер по продажам B2B (промышленное оборудование)",
        {"duties", "requirements", "nice_to_have", "conditions"},
    ),
    "lawyer.txt": (
        "юрист по договорной работе",
        {"duties", "requirements", "nice_to_have", "conditions"},
    ),
    "engineer_en.txt": (
        "Mechanical Design Engineer",
        {"about", "duties", "requirements", "nice_to_have", "conditions"},
    ),
}


@pytest.mark.parametrize("name", list(OTHER))
def test_other_profession_vacancies(name: str) -> None:
    path = FIXTURES / "vacancies_other" / name
    doc = load_document(path.read_bytes(), name, DocKind.vacancy, "V1")
    title, roles = OTHER[name]
    assert doc.title == title
    assert roles <= {f.section_role for f in doc.fragments}
    assert not [w for w in doc.warnings if "не найдены разделы" in w]


def test_docx_vacancy_with_heading_styles() -> None:
    import docx

    d = docx.Document()
    d.add_heading("Инженер-сметчик", level=1)
    d.add_heading("Обязанности", level=2)
    d.add_paragraph("Составление локальных смет по ГЭСН и ФЕР.", style="List Bullet")
    d.add_heading("Требования", level=2)
    d.add_paragraph("Опыт работы сметчиком от 2 лет, знание Гранд-Сметы.", style="List Bullet")
    buf = io.BytesIO()
    d.save(buf)
    doc = load_document(buf.getvalue(), "v.docx", DocKind.vacancy, "V1")
    assert doc.title == "Инженер-сметчик"
    roles = [f.section_role for f in doc.fragments]
    assert roles == ["about", "duties", "duties", "requirements", "requirements"]
    assert doc.fragments[2].source == FragmentSource.list_item


# ---------- имена файлов ----------


@pytest.mark.parametrize(
    ("raw", "fixed"),
    [
        ("Вакансия 1.docx".encode("cp1251").decode("latin-1"), "Вакансия 1.docx"),
        ("резюме.pdf".encode().decode("latin-1"), "резюме.pdf"),
        ("Вакансия 1.docx", "Вакансия 1.docx"),
        ("café.docx", "café.docx"),
        ("Müller_résumé.pdf", "Müller_résumé.pdf"),
        ("plain.txt", "plain.txt"),
    ],
)
def test_fix_filename(raw: str, fixed: str) -> None:
    assert fix_filename(raw) == fixed


# ---------- эталон по документам кейса (структура проверена глазами 12.11) ----------

_RESUME_ROLES = {"contacts", "about", "experience", "skills", "education"}
CASE_EXPECTED = {
    "Вакансия 1.docx": (30, {"about", "duties", "requirements", "nice_to_have", "conditions"}),
    "Вакансия 2.docx": (27, {"about", "duties", "requirements", "conditions"}),
    "Вакансия 3.docx": (28, {"about", "duties", "requirements", "nice_to_have", "conditions"}),
    "Иванов Алексей_резюме 1.docx": (73, _RESUME_ROLES),
    "Петров Иван_резюме 2.docx": (107, _RESUME_ROLES),
    "Петрова Лилия_резюме 4.docx": (47, _RESUME_ROLES),
    "Семенов Алексей _резюме 3.docx": (45, _RESUME_ROLES),
}


@pytest.mark.parametrize("name", list(CASE_EXPECTED))
def test_case_documents(name: str) -> None:
    kind = DocKind.resume if "резюме" in name else DocKind.vacancy
    path = CASE_DIR / name
    doc = load_document(path.read_bytes(), name, kind, _doc_id(kind))
    count, roles = CASE_EXPECTED[name]
    assert len(doc.fragments) == count
    assert set(Counter(f.section_role for f in doc.fragments)) == roles
    assert not doc.warnings
    if kind == DocKind.resume:
        experience = sum(f.section_role == "experience" for f in doc.fragments)
        assert experience >= 15  # опыт работы не потерян в «контактах»
    else:
        assert doc.title
        assert len(doc.title) < 100
