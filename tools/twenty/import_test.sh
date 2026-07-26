#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)

project=leonaid-poc033-test
port=18085
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
fixture="$root/tests/fixtures/golden/v1"
workbook_host="$fixture/outputs/019f9a37-b6da-7521-b590-ec1e8215a6bf/leonaid-crm-import.xlsx"
workbook_container="/repo/tests/fixtures/golden/v1/outputs/019f9a37-b6da-7521-b590-ec1e8215a6bf/leonaid-crm-import.xlsx"
proof=$(mktemp -d)
host_user_id=$(id -u)
host_group_id=$(id -g)

if [ ! -f "$env_file" ]; then
  echo "crm-import-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap ausführen" >&2
  exit 1
fi
if [ ! -f "$workbook_host" ]; then
  echo "crm-import-test: ERROR: Golden-Arbeitsmappe fehlt: $workbook_host" >&2
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
    echo "crm-import-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    diagnose
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

run_python() {
  compose run --rm --no-deps \
    --user "$host_user_id:$host_group_id" \
    --env-from-file "$env_file" \
    --env-from-file "$proof/integration.env" \
    --env PYTHONPATH=/repo/src:/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api "$@"
}

provision() {
  compose run --rm --no-deps \
    --user "$host_user_id:$host_group_id" \
    --env-from-file "$env_file" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api tools/twenty/provision.py apply \
    --token-output /proof/integration.env \
    --snapshot-output /proof/schema.json
}

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api
compose up --detach --wait --wait-timeout 420 twenty-server twenty-worker
provision
run_python tools/seed/golden.py seed-twenty /repo/tests/fixtures/golden/v1

echo "crm-import-test: Dry Run zeigt new, update, conflict und rejected"
run_python tools/twenty/import_contacts.py dry-run \
  "$workbook_container" \
  --sheet Kontakte \
  --report /proof/dry.json

echo "crm-import-test: erster Lauf legt neu an und aktualisiert kontrolliert"
run_python tools/twenty/import_contacts.py apply \
  "$workbook_container" \
  --sheet Kontakte \
  --report /proof/first.json

echo "crm-import-test: zweiter Lauf aktualisiert genau einen Datensatz"
run_python tools/twenty/import_contacts.py apply \
  "$workbook_container" \
  --sheet "Kontakte Update" \
  --report /proof/second.json

echo "crm-import-test: Wiederholung ist idempotent"
run_python tools/twenty/import_contacts.py apply \
  "$workbook_container" \
  --sheet "Kontakte Update" \
  --report /proof/repeat.json

run_python tools/twenty/import_contract.py \
  --dry /proof/dry.json \
  --first /proof/first.json \
  --second /proof/second.json \
  --repeat /proof/repeat.json

echo "crm-import-test: OK: Golden-XLSX über echte Twenty-API reproduzierbar importiert"
