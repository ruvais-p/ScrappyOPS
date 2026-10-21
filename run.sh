#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/backend/docker-compose.dev.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or is not on PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user start docker-desktop 2>/dev/null || true
  fi

  echo "Waiting for Docker Desktop..."
  for _ in {1..60}; do
    if docker info >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop, then run ./run.sh again." >&2
  exit 1
fi

echo "Building and starting ScrappyOPS..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "Waiting for the backend health check..."
for _ in {1..30}; do
  if docker compose -f "$COMPOSE_FILE" exec -T web python -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=2)' \
    >/dev/null 2>&1; then
    echo
    echo "ScrappyOPS is ready: http://127.0.0.1:8000"
    echo "HQ login: hq@scrappy.test"
    echo "Password: Scrappy#2026"
    exit 0
  fi
  sleep 2
done

echo "The backend did not become healthy. Recent logs:"
docker compose -f "$COMPOSE_FILE" logs --tail=60 web
exit 1
