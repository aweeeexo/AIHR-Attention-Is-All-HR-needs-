"""D57: атомарность требований — личные качества через «и», пункты, склеенные из разных строк."""

from aihr.contracts import Fragment, FragmentSource, Modality, ReqKind, Requirement
from aihr.extract.requirements import split_glued, split_soft


def _req(
    text: str, kind: ReqKind = ReqKind.soft, alternatives=(), sources=("V1.3",)
) -> Requirement:
    return Requirement(id="", vacancy_id="V1", text=text, kind=kind, modality=Modality.must,
                       modality_marker=None, modality_reason="", alternatives=list(alternatives),
                       source_fragment_ids=list(sources))  # fmt: skip


def _frag(fid: str, text: str) -> Fragment:
    return Fragment(id=fid, order=int(fid.split(".")[1]), section=None, section_role="requirements",
                    source=FragmentSource.list_item, text=text, masked_text=text)  # fmt: skip


def test_soft_pair_is_split_with_shared_head() -> None:
    out = split_soft([_req("Высокий уровень пунктуальности и стрессоустойчивости")])
    assert [r.text for r in out] == [
        "Высокий уровень пунктуальности",
        "Высокий уровень стрессоустойчивости",
    ]


def test_soft_list_without_head() -> None:
    out = split_soft([_req("Внимательность, усидчивость и аккуратность")])
    assert [r.text for r in out] == ["Внимательность", "Усидчивость", "Аккуратность"]


def test_soft_split_keeps_non_parallel_phrases() -> None:
    reqs = [
        _req("Умение работать в команде и самостоятельно"),
        _req("Развитые коммуникативные навыки"),
        _req("Знание Python и SQL", kind=ReqKind.skill),
    ]
    assert [r.text for r in split_soft(reqs)] == [r.text for r in reqs]


def test_glued_lines_become_one_requirement_per_line() -> None:
    frags = [
        _frag("V1.4", "Знание AutoCAD и норм оформления чертежей"),
        _frag("V1.5", "Revit: семейства, спецификации"),
        _frag("V1.6", "Navisworks: проверка коллизий"),
    ]
    glued = _req(
        "Знание AutoCAD и норм оформления чертежей",
        kind=ReqKind.skill,
        alternatives=["AutoCAD", "Revit", "Navisworks"],
        sources=["V1.4", "V1.5", "V1.6"],
    )
    other = _req("Revit: семейства", kind=ReqKind.skill, sources=["V1.5"])
    out = split_glued([glued, other], frags)
    assert [(r.text, r.source_fragment_ids) for r in out] == [
        ("Знание AutoCAD и норм оформления чертежей", ["V1.4"]),
        ("Navisworks: проверка коллизий", ["V1.6"]),
        ("Revit: семейства", ["V1.5"]),  # V1.5 уже покрыта своим требованием — дубль не создаём
    ]


def test_enumeration_in_one_line_is_not_glued() -> None:
    frags = [_frag("V1.4", "Опыт с AutoCAD, Revit")]
    req = _req(
        "Опыт с AutoCAD, Revit",
        kind=ReqKind.skill,
        alternatives=["AutoCAD", "Revit"],
        sources=["V1.4"],
    )
    assert split_glued([req], frags) == [req]
