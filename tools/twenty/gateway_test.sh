#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)

project=leonaid-poc031-test
port=18084
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
proof=$(mktemp -d)
host_user_id=$(id -u)
host_group_id=$(id -g)

if [ ! -f "$env_file" ]; then
  echo "twenty-gateway-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap ausführen" >&2
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
    echo "twenty-gateway-test: Diagnose der fehlgeschlagenen echten Services:" >&2
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
    --env PYTHONPATH=/repo/src:/workspace/src \
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

echo "twenty-gateway-test: führt CRUD, echte Batches und Cursor-Pagination aus"
run_python tools/twenty/gateway_contract.py exercise --state /proof/state.json

echo "twenty-gateway-test: stoppt Twenty real und erwartet sichere Fehler"
compose stop twenty-server
run_python tools/twenty/gateway_contract.py expect-outage --state /proof/state.json

echo "twenty-gateway-test: startet Twenty neu und prüft alle bestätigten Daten"
compose up --detach --wait --wait-timeout 420 twenty-server
run_python \
  tools/twenty/gateway_contract.py verify-after-restart --state /proof/state.json

echo "twenty-gateway-test: OK: CRM-Port, Pagination und Ausfallvertrag real bewiesen"
