"""D51: качество вакансии — непроверяемое, расплывчатое, «единорог», дискриминация, дубли."""

from fastapi.testclient import TestClient

from aihr.api.app import app
from aihr.config import get_settings
from aihr.contracts import Modality, ReqKind, Requirement, Threshold, ThresholdKind
from aihr.pipeline import run
from aihr.report.vacancy_check import MAX_MUST, check_vacancy
from tests.conftest import fixture_file


def _req(i: int, text: str, line: int | None = None, **kw) -> Requirement:
    return Requirement(
        id=f"V1.req{i}", vacancy_id="V1", text=text, kind=kw.pop("kind", ReqKind.skill),
        modality=kw.pop("modality", Modality.must), modality_marker=None, modality_reason="",
        source_fragment_ids=[f"V1.{line or i}"], **kw,
    )  # fmt: skip


def kinds(check) -> list[str]:
    return [i.kind for i in check.issues]


def test_discriminatory_and_vague_and_unverifiable() -> None:
    c = check_vacancy("V1", [
        _req(1, "Мужчина до 35 лет включительно"),
        _req(2, "Уверенное владение AutoCAD"),
        _req(3, "Стрессоустойчивость", kind=ReqKind.soft, verifiable=False),
        _req(4, "Опыт сметной работы от 3 лет",
             threshold=Threshold(kind=ThresholdKind.years, value="3", subject="сметы")),
    ])  # fmt: skip
    assert kinds(c) == ["discriminatory", "vague", "unverifiable"]
    assert "дискриминац" in c.summary and "в интервью" in c.summary


def test_concrete_vacancy_has_no_issues() -> None:
    c = check_vacancy("V1", [_req(1, "Работа в AutoCAD"), _req(2, "Опыт продаж от 2 лет")])
    assert c.issues == [] and "замечаний нет" in c.summary


def test_unicorn_counts_vacancy_lines_not_split_items() -> None:
    many = [_req(i, f"Навык номер {i}") for i in range(1, MAX_MUST + 2)]
    assert "too_many_must" in kinds(check_vacancy("V1", many))
    split = [_req(i, f"Навык номер {i}", line=1) for i in range(1, MAX_MUST + 2)]
    assert "too_many_must" not in kinds(check_vacancy("V1", split))  # одно перечисление


def test_duplicates_but_not_parts_of_one_enumeration() -> None:
    dup = check_vacancy("V1", [_req(1, "Опыт ведения договорной работы с поставщиками"),
                               _req(2, "Опыт договорной работы с поставщиками")])  # fmt: skip
    assert "duplicate" in kinds(dup)
    same_line = check_vacancy(
        "V1",
        [
            _req(1, "Опыт договорной работы с поставщиками", line=1),
            _req(2, "Опыт договорной работы с подрядчиками", line=1),
        ],
    )
    assert "duplicate" not in kinds(same_line)


def test_vacancy_check_api() -> None:
    r = run(fixture_file("resume_cook.txt"), [fixture_file("vacancy_cook.txt")])
    client = TestClient(app)
    got = client.get(f"/runs/{r.run_id}/vacancy-check")
    assert got.status_code == 200 and got.json()[0]["vacancy_id"] == "V1"
    assert client.get("/runs/20260101-000000-abcdef/vacancy-check").status_code == 404
    get_settings.cache_clear()
