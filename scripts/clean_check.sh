#!/usr/bin/env bash
# Проверка «как у жюри» (T12): чистый клон → .env из примера → сборка и запуск → health →
# пример из кейса через API → use cases в контейнере → UI отвечает → остановка и уборка.
# Нужны только git, Docker и curl. Порты 8000 и 8501 должны быть свободны.
#
#   bash scripts/clean_check.sh [репозиторий] [ветка или тег]
set -euo pipefail

REPO=${1:-git@github.com:aweeeexo/AIHR-Attention-Is-All-HR-needs-.git}
REF=${2:-main}
PROJECT=aihr-clean
DIR=$(mktemp -d)

cleanup() {
  if [ -d "$DIR/aihr" ]; then
    (cd "$DIR/aihr" && docker compose -p "$PROJECT" down -v --remove-orphans >/dev/null 2>&1) || true
  fi
  rm -rf "$DIR"
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$1"; }

step "клон $REF в $DIR"
git clone --quiet --depth 1 --branch "$REF" "$REPO" "$DIR/aihr"
cd "$DIR/aihr"
cp .env.example .env

step "сборка и запуск (docker compose up --build)"
started=$(date +%s)
docker compose -p "$PROJECT" up --build -d
echo "собрано и запущено за $(( $(date +%s) - started )) с"

step "ждём /health"
for _ in $(seq 1 90); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://localhost:8000/health
echo

step "пример из кейса через API"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8000/match/example)
[ "$code" = "200" ] || { echo "POST /match/example вернул $code"; exit 1; }
echo "POST /match/example: 200"

step "use cases в контейнере (aihr demo)"
docker compose -p "$PROJECT" run --rm api aihr demo

step "UI"
for _ in $(seq 1 30); do
  if curl -fsS http://localhost:8501/_stcore/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://localhost:8501/_stcore/health
echo

printf '\nчистый запуск: всё в порядке (%s с)\n' "$(( $(date +%s) - started ))"
