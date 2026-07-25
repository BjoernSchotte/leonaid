#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
project=leonaid-poc020-test
port=18083
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"

if [ ! -f "$env_file" ]; then
  echo "poc020-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose() {
  LEONAID_HTTP_PORT="$port" docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "poc020-test: Diagnose der realen Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=100 api core-postgres >&2 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

compose down --volumes --remove-orphans >/dev/null 2>&1 || true

echo "poc020-test: startet realen ASGI-Server aus leeren Compose-Volumes"
compose up --build --detach --wait --wait-timeout 420

compose run --rm --no-deps \
  --env LEONAID_INTEGRATION_BASE_URL=http://api:8000 \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/core/smoke.py

echo "poc020-test: OK: Schichtengrenzen und reale Plattformintegration bewiesen"
