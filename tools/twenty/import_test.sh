#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_CRM_IMPORT_TEST_PROJECT:-leonaid-poc033-test}-$suffix
owned=false
port=18085
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
fixture="$root/tests/fixtures/golden/v1"
workbook_host="$fixture/outputs/019f9a37-b6da-7521-b590-ec1e8215a6bf/leonaid-crm-import.xlsx"
workbook_container="/repo/tests/fixtures/golden/v1/outputs/019f9a37-b6da-7521-b590-ec1e8215a6bf/leonaid-crm-import.xlsx"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
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
    --file "$isolation_file" \
    "$@"
}

diagnose() {
  compose ps >&2 || true
  compose logs --no-color --tail=120 twenty-server twenty-worker >&2 || true
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && { [ "$owned" = true ] || [ -n "${LEONAID_TEST_STACK:-}" ]; }; then
    echo "crm-import-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    diagnose
  fi
  if [ "$owned" = true ]; then
    if ! compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    for inventory in containers volumes networks; do
      case "$inventory" in
        containers) remaining=$(docker ps -aq --filter "label=com.docker.compose.project=$project") || status=1 ;;
        volumes) remaining=$(docker volume ls -q --filter "label=com.docker.compose.project=$project") || status=1 ;;
        networks) remaining=$(docker network ls -q --filter "label=com.docker.compose.project=$project") || status=1 ;;
      esac
      if [ -n "$remaining" ]; then
        echo "test-isolation: owned $inventory remain for $project" >&2
        status=1
      fi
    done
    if [ "$status" -eq 0 ]; then echo "test-isolation: $project passed and owned resources were removed"; fi
  fi
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ -z "${LEONAID_TEST_STACK:-}" ]; then
# Refuse existing resources and unreadable inventories before Docker mutations.
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$root/tools/surveys/network_override.py" "$isolation_file"
owned=true
compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
fi

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

if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services="twenty-server twenty-worker"
  . "$root/tools/testing/borrow_stack.sh"
else
compose build api
echo "crm-import-test: wartet auf die TCP-Bereitschaft von Postgres und Redis"
compose up --detach --wait --wait-timeout 180 twenty-postgres twenty-redis
compose up --detach --wait --wait-timeout 420 twenty-server twenty-worker
provision
fi
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
