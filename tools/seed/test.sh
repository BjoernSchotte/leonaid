#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=leonaid-poc012-test
port=18082
https_port=18445
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
fixture="$root/tests/fixtures/golden/v1"
snapshot_directory="$root/.local/snapshots"

if [ ! -f "$env_file" ]; then
  echo "seed-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap ausführen" >&2
  exit 1
fi

export LEONAID_COMPOSE_PROJECT="$project"
export LEONAID_HTTP_PORT="$port"
export LEONAID_HTTPS_PORT="$https_port"

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --profile dev-mail \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "seed-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=100 >&2 || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true

echo "seed-test: beweist Ablehnung eines Produktions-DSN vor jeder Löschung"
if compose config --format json |
  sed 's/@core-postgres:/@production-db.example.com:/' |
  docker run --rm -i \
    -v "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/seed/safety.py \
    --project-name "$project" \
    --env-file /workspace/.env.local; then
  echo "seed-test: ERROR: Produktions-DSN wurde nicht abgewiesen" >&2
  exit 1
fi

echo "seed-test: setzt alle vier Systeme aus leeren Volumes auf Golden Data v1"
"$root/leonaid" reset
"$root/leonaid" snapshot poc012-first.json
docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/seed/verify_snapshot.py golden \
  /repo/.local/snapshots/poc012-first.json \
  /repo/tests/fixtures/golden/v1

echo "seed-test: führt einen zweiten idempotenten Seed aus"
"$root/leonaid" seed
"$root/leonaid" snapshot poc012-second.json
docker run --rm \
  -v "$root/.local:/local:ro" \
  "$ALPINE_IMAGE" \
  cmp /local/snapshots/poc012-first.json /local/snapshots/poc012-second.json

echo "seed-test: verändert PostgreSQL, Twenty, RustFS und Mailpit real"
compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py mutate /repo/tests/fixtures/golden/v1
"$root/leonaid" snapshot poc012-mutated.json
docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/seed/verify_snapshot.py mutated \
  /repo/.local/snapshots/poc012-mutated.json \
  /repo/tests/fixtures/golden/v1
if docker run --rm \
  -v "$root/.local:/local:ro" \
  "$ALPINE_IMAGE" \
  cmp -s /local/snapshots/poc012-first.json /local/snapshots/poc012-mutated.json; then
  echo "seed-test: ERROR: absichtliche Mutation änderte den Snapshot nicht" >&2
  exit 1
fi

echo "seed-test: Reset stellt den exakten fachlichen Snapshot wieder her"
"$root/leonaid" reset
"$root/leonaid" snapshot poc012-restored.json
docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/seed/verify_snapshot.py golden \
  /repo/.local/snapshots/poc012-restored.json \
  /repo/tests/fixtures/golden/v1
docker run --rm \
  -v "$root/.local:/local:ro" \
  "$ALPINE_IMAGE" \
  cmp /local/snapshots/poc012-first.json /local/snapshots/poc012-restored.json

echo "seed-test: OK: Sicherheit, Idempotenz, Mutation und exakter Reset bewiesen"
