"""Отложенный набор (D57): разметка сделана 14.11 до первого прогона пайплайна на этих документах.

Профессии не из кейса и не из эталона, люди вымышлены. Рубрика та же, что в eval/golden:
«Не соответствует» — только при факте против требования, ниже порога или часть — «Частично».
Запуск: uv run python eval/holdout/make_golden.py → eval/holdout/golden/*.json
Вакансия H4 считается в паре одна, поэтому её фрагменты — V1.*, а не V4.*
"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "golden"
M, N = "match", "partial"
X, S = "mismatch", "not_stated"

VACANCIES = {
    "Вакансия H1.txt": [
        ("V1.4", "nice", "разработка разделов ОВ ВК стадиях"),
        ("V1.5", "nice", "спецификаций оборудования Excel"),
        ("V1.6", "nice", "согласование решений смежными отделами"),
        ("V1.8", "must", "высшее техническое образование"),
        ("V1.9", "must", "опыт проектирования систем вентиляции"),
        ("V1.10", "must", "владение AutoCAD"),
        ("V1.11", "must", "Revit семейств спецификаций"),
        ("V1.12", "must", "знание СП 60.13330 норм"),
        ("V1.13", "must", "внимательность"),
        ("V1.13", "must", "аккуратность"),
        ("V1.15", "nice", "Navisworks"),
        ("V1.16", "nice", "английский язык B1"),
    ],
    "Вакансия H2.txt": [
        ("V2.4", "nice", "планирование маршрутов загрузки автопарка"),
        ("V2.5", "nice", "отчётности рейсам Excel Power BI"),
        ("V2.6", "nice", "работа перевозчиками клиентами"),
        ("V2.8", "must", "опыт работы логистом"),
        ("V2.9", "must", "знание 1С управление торговлей логистикой"),
        ("V2.10", "must", "Excel ВПР сводные таблицы"),
        ("V2.11", "must", "стрессоустойчивость"),
        ("V2.11", "must", "пунктуальность"),
        ("V2.12", "must", "высшее образование"),
        ("V2.14", "nice", "водительское удостоверение категории B"),
        ("V2.15", "nice", "международными перевозками"),
    ],
    "Вакансия H3.txt": [
        ("V3.4", "nice", "реклама Яндекс Директ"),
        ("V3.5", "nice", "анализ трафика Яндекс Метрике Google Analytics"),
        ("V3.6", "nice", "контента сайта соцсетей"),
        ("V3.8", "must", "опыт интернет-маркетинге"),
        ("V3.9", "must", "настройки контекстной рекламы"),
        ("V3.10", "must", "аналитикой отчёты воронки конверсии"),
        ("V3.11", "must", "грамотная письменная речь"),
        ("V3.12", "must", "креативность"),
        ("V3.12", "must", "инициативность"),
        ("V3.14", "nice", "продвижения медицинских услуг"),
        ("V3.15", "nice", "навыки Photoshop"),
    ],
    "Вакансия H4.txt": [
        ("V1.3", "nice", "приготовление блюд европейской кухни технологическим картам"),
        ("V1.4", "nice", "контроль качества заготовок"),
        ("V1.6", "must", "опыт работы поваром"),
        ("V1.7", "must", "среднее профессиональное образование специальности"),
        ("V1.8", "must", "санитарная книжка"),
        ("V1.9", "nice", "пароконвектоматом"),
    ],
}

HA, HB = "Котов Денис_резюме HA.txt", "Ильина Марина_резюме HB.txt"
HC, HD = "Орлова Светлана_резюме HC.txt", "Смирнова Анна_резюме HD.txt"
H1, H2, H3, H4 = VACANCIES

LABELS = {
    # проектировщик: ВК не делал, спецификации без Excel, Revit по готовым семействам, английский A2
    (HA, H1): [N, N, M, M, M, M, N, M, S, S, S, N],
    (HA, H2): [S, S, S, S, S, S, S, S, M, S, S],
    (HA, H3): [S] * 11,
    # логист: Power BI нет, другая конфигурация 1С, СПО вместо высшего, по России
    (HB, H1): [S, S, S, X, S, S, S, S, S, S, S, S],
    (HB, H2): [M, N, M, M, N, M, S, M, X, M, S],
    (HB, H3): [S] * 11,
    # маркетолог: нет Google Analytics, нет сайта, высшее не техническое
    (HC, H1): [S, S, S, N, S, S, S, S, S, S, S, S],
    (HC, H2): [S, S, S, S, S, S, S, S, M, S, S],
    (HC, H3): [M, N, N, M, M, M, S, S, S, M, M],
    # повар: за заготовки отвечает, контроль качества прямо не назван
    (HD, H4): [M, N, M, M, M, M],
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for i, (vfile, items) in enumerate(VACANCIES.items(), 1):
        req = {"vacancy_file": vfile, "items": [
            {"key": k, "fragment_ids": [f], "modality": m} for f, m, k in items]}  # fmt: skip
        (OUT / f"requirements_H{i}.json").write_text(
            json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    for (rfile, vfile), statuses in LABELS.items():
        items = VACANCIES[vfile]
        assert len(statuses) == len(items), (rfile, vfile)
        rows = [{"key": k, "status": s} for (_, _, k), s in zip(items, statuses, strict=True)]
        out = {"resume_file": rfile, "vacancy_file": vfile, "items": rows}
        name = f"verdicts_{rfile.split()[-1][:-4]}_{vfile.split()[-1][:-4]}.json"
        (OUT / name).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
