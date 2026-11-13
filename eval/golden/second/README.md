# Вторая разметка

Шаблоны созданы для трёх пар из задания. Поля `annotator` и `status` оставлены пустыми
для второго человека. Чтобы увидеть требования и фрагменты резюме с номерами, запустите
из корня проекта:

```sh
uv run python scripts/label_pair.py R2 V1
uv run python scripts/label_pair.py R4 V2
uv run python scripts/label_pair.py R1 V3
```

Заполните в каждом файле `annotator`, а у каждого требования — `status`, `fragment_ids`
и `evidence_type` по рубрике из `docs/teammate_tasks.md`. До окончания разметки используйте
только исходные документы и требования. После заполнения всех трёх файлов посчитайте
согласие командой `uv run python eval/agreement.py`.
