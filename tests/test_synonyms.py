"""T06-A: словарь синонимов — каноны, классы, омонимы, поиск терминов в тексте."""

from pathlib import Path

import pytest
import yaml

from aihr.config import get_settings
from aihr.normalize import aliases, canonicalize, find_terms, normalize_text, skill_class
from tests.conftest import REPO_ROOT


@pytest.mark.parametrize(
    ("term", "canon"),
    [
        ("JS", "javascript"), ("ECMAScript", "javascript"), ("TypeScript", "typescript"),
        ("C#", "csharp"), ("c++", "cpp"), ("Golang", "go"), ("Python 3.11", "python"),
        ("Postgres", "postgresql"), ("k8s", "kubernetes"), ("1С", "one_c"), ("1c", "one_c"),
        ("1С:Бухгалтерия", "one_c"), ("МСФО", "ifrs"), ("Гугл таблицы", "google_sheets"),
        ("Эксель", "excel"), ("Автокад", "autocad"), ("Компас-3D", "kompas"),
        ("Забор венозной крови", "venipuncture"), ("Санкнижка", "sanitary_book"),
        ("ГК РФ", "civil_code"), ("Английский язык", "english"), ("Ёлка", None),
    ],
)  # fmt: skip
def test_canonicalize(term: str, canon: str | None) -> None:
    assert canonicalize(term) == canon


@pytest.mark.parametrize(
    ("a", "b"),
    [("Java", "JavaScript"), ("C#", "C++"), ("Excel", "Google Sheets"), ("Revit", "AutoCAD")],
)
def test_different_things_are_not_merged(a: str, b: str) -> None:
    assert canonicalize(a) != canonicalize(b)


def test_c_and_homonyms_are_not_guessed() -> None:
    assert canonicalize("C") is None  # одна буква — не склеиваем с C# и C++
    assert canonicalize("ОС") is None  # основные средства или операционная система — решит LLM
    assert find_terms("опыт работы с ОС и ПК") == []


def test_classes_for_adjacent_skills() -> None:
    assert skill_class("revit") == skill_class("archicad") == "bim"
    assert skill_class("excel") == skill_class("google_sheets") == "spreadsheet"
    assert canonicalize("Excel") != canonicalize("Google Sheets")  # смежные, но не синонимы
    assert "js" in aliases("javascript")


def test_find_terms_in_text() -> None:
    text = "Вёл учёт в 1С, строил отчёты в Power BI, писал на C# и Python 3; знание МСФО."
    assert find_terms(text) == ["one_c", "power_bi", "csharp", "python", "ifrs"]
    assert find_terms("Учёт основных средств и ТМЦ") == ["fixed_assets", "inventory_items"]
    assert find_terms("javascript-разработчик") == ["javascript"]
    assert find_terms("Kotlin") == ["kotlin"] and find_terms("котлеты") == []


def test_normalize_text() -> None:
    assert normalize_text("Знаю JS и 1С") == "знаю javascript и one_c"


def test_dictionary_is_general_and_consistent() -> None:
    raw = yaml.safe_load((REPO_ROOT / "data" / "synonyms.yaml").read_text(encoding="utf-8"))
    terms = raw["terms"]
    assert 200 <= len(terms) <= 400
    all_aliases = [str(a).lower() for t in terms.values() for a in t["aliases"]]
    assert len(all_aliases) == len(set(all_aliases)), "один алиас у двух канонов"
    assert all(t.get("class") for t in terms.values())


def test_missing_dictionary_disables_layer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SYNONYMS_PATH", str(tmp_path / "нет.yaml"))
    get_settings.cache_clear()
    assert canonicalize("JS") is None and find_terms("JS") == []
