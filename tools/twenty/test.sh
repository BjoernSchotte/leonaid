#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=leonaid-poc030-test
port=18083
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
proof=$(mktemp -d)
host_user_id=$(id -u)
host_group_id=$(id -g)

if [ ! -f "$env_file" ]; then
  echo "twenty-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap ausführen" >&2
  exit 1
fi

export LEONAID_HTTP_PORT="$port"

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    "$@"
}

diagnose() {
  compose ps >&2 || true
  compose logs --no-color --tail=120 twenty-server twenty-worker >&2 || true
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "twenty-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    diagnose
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

run_tool() {
  compose run --rm --no-deps \
    --user "$host_user_id:$host_group_id" \
    --env-from-file "$env_file" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api tools/twenty/provision.py "$@"
}

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api
compose up --detach --wait --wait-timeout 420 twenty-server twenty-worker

echo "twenty-test: provisioniert eine leere Twenty-Instanz über die Metadata API"
run_tool apply \
  --token-output /proof/integration.env \
  --snapshot-output /proof/first.json

echo "twenty-test: wiederholt die Provisionierung ohne Duplikate oder Drift"
run_tool apply \
  --token-output /proof/integration.env \
  --snapshot-output /proof/second.json
docker run --rm \
  --volume "$proof:/proof:ro" \
  "$ALPINE_IMAGE" \
  cmp /proof/first.json /proof/second.json

echo "twenty-test: beweist erlaubte und verweigerte Integrations-Key-Rechte"
run_tool verify-key --token-file /proof/integration.env

echo "twenty-test: verändert ein echtes Feld und erwartet verständlichen Drift"
run_tool mutate-field \
  --object charityAction \
  --field goalValue \
  --label "ABSICHTLICHER POC-030 DRIFT"
if run_tool check >"$proof/drift.log" 2>&1; then
  echo "twenty-test: ERROR: absichtlicher Feld-Drift wurde nicht erkannt" >&2
  exit 1
fi
if ! grep -F "objects.charityAction.fields.goalValue.label" "$proof/drift.log" >/dev/null; then
  echo "twenty-test: ERROR: Drift-Diagnose nennt den Feldpfad nicht" >&2
  sed -n '1,120p' "$proof/drift.log" >&2
  exit 1
fi
if ! grep -F "ABSICHTLICHER POC-030 DRIFT" "$proof/drift.log" >/dev/null; then
  echo "twenty-test: ERROR: Drift-Diagnose nennt den vorhandenen Wert nicht" >&2
  sed -n '1,120p' "$proof/drift.log" >&2
  exit 1
fi

echo "twenty-test: OK: Idempotenz, Drift und Least Privilege real bewiesen"
