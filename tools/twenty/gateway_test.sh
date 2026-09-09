#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc031-test-$suffix
owned=false
port=18084
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
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
    echo "twenty-gateway-test: Diagnose der fehlgeschlagenen echten Services:" >&2
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

if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services="twenty-server twenty-worker"
  . "$root/tools/testing/borrow_stack.sh"
else
compose build api
compose up --detach --wait --wait-timeout 420 twenty-server twenty-worker
provision
fi

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
