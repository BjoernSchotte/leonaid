#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
project=leonaid-poc021-test
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"

if [ ! -f "$env_file" ]; then
  echo "poc021-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "poc021-test: Diagnose der realen Core-Datenbank:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=100 core-postgres >&2 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

compose down --volumes --remove-orphans >/dev/null 2>&1 || true

docker run --rm \
  -v "$root:/repo:ro" \
  docker.io/library/python:3.13.13-slim-trixie@sha256:aa938a849bcb82dce8f49480f056ab82bf5c1c3ebc294f0430f37b6820e7f286 \
  python /repo/tools/schema/check_migrations.py /repo/migrations/versions

echo "poc021-test: migriert eine vollständig leere PostgreSQL-Instanz bis Head"
compose build api
compose up --detach --wait --wait-timeout 120 core-postgres
compose run --rm --no-deps --entrypoint alembic api upgrade head
compose run --rm --no-deps --entrypoint alembic api upgrade head
compose run --rm --no-deps \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/schema/smoke.py

echo "poc021-test: migriert den versionierten Vorgänger-Snapshot samt Daten"
compose down --volumes --remove-orphans
compose up --detach --wait --wait-timeout 120 core-postgres
compose run --rm --no-deps --entrypoint alembic api upgrade 0011_public_orders
compose exec -T core-postgres sh -ec \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  <"$root/tests/fixtures/schema/v0.sql"
compose run --rm --no-deps --entrypoint alembic api upgrade head
compose run --rm --no-deps \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/schema/smoke.py --legacy

echo "poc021-test: OK: Leeraufbau, Upgrade, Constraints und Datenhalt bewiesen"
