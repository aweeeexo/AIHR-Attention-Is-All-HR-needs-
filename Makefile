# Linux, macOS и жюри. На Windows те же команды: uv run poe <цель>.
# Цели с Docker не требуют uv на машине; test, lint, eval, check-leak — требуют (https://docs.astral.sh/uv/).

.PHONY: help up down demo test test-docker clean-check lint eval check-leak

help:
	@echo "up          собрать образ и поднять API (8000) и UI (8501)"
	@echo "down        остановить сервисы"
	@echo "demo        прогон примера из кейса в контейнере и проверка результата"
	@echo "test        тесты (uv)"
	@echo "test-docker тесты в Linux-контейнере (нужен только Docker)"
	@echo "clean-check чистый клон, сборка, запуск и проверка примера — как у жюри"
	@echo "lint        ruff"
	@echo "eval        метрики на золотом наборе -> eval/report.md"
	@echo "check-leak  слова из вакансий кейса в src/"

up:
	docker compose up --build

down:
	docker compose down

demo:
	docker compose run --rm api aihr demo

test-docker:
	docker build --target test -t aihr-test .
	docker run --rm aihr-test

clean-check:
	bash scripts/clean_check.sh

test:
	uv run poe test

lint:
	uv run poe lint

eval:
	uv run poe eval

check-leak:
	uv run poe check-leak
