#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/backend/docker-compose.dev.yml"
ACTION="${1:-start}"

usage() {
  cat <<'EOF'
Usage: ./run.sh [start|stop|restart|build|status]

  start     Start ScrappyOPS using the local image (default)
  stop      Stop the web and database containers; data is preserved
  restart   Stop and start ScrappyOPS using the local image
  build     Rebuild the image, then start ScrappyOPS (needs internet if base images are not cached)
  status    Show the current container status
EOF
}

case "$ACTION" in
  start|stop|restart|build|status) ;;
  -h|--help|help) usage; exit 0 ;;
  *) echo "Unknown command: $ACTION" >&2; usage >&2; exit 2 ;;
esac

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

if [[ "$ACTION" == "stop" ]]; then
  echo "Stopping ScrappyOPS..."
  docker compose -f "$COMPOSE_FILE" stop
  echo "ScrappyOPS stopped. Database data has been preserved."
  exit 0
fi

if [[ "$ACTION" == "status" ]]; then
  docker compose -f "$COMPOSE_FILE" ps
  exit 0
fi

if [[ "$ACTION" == "restart" ]]; then
  echo "Stopping ScrappyOPS before restart..."
  docker compose -f "$COMPOSE_FILE" stop
fi

if [[ "$ACTION" == "build" ]]; then
  echo "Building and starting ScrappyOPS..."
  docker compose -f "$COMPOSE_FILE" up -d --build
else
  if ! docker image inspect backend-web:latest >/dev/null 2>&1; then
    echo "The local ScrappyOPS image is missing; building it now..."
    docker compose -f "$COMPOSE_FILE" up -d --build
  else
    echo "Starting ScrappyOPS from the local image..."
    docker compose -f "$COMPOSE_FILE" up -d --no-build
  fi
fi

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
