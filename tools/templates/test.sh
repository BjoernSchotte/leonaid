#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_TEMPLATE_TEST_PROJECT:-leonaid-poc051-test}-$suffix
owned=false
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
host_user_id=$(id -u)
host_group_id=$(id -g)

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && { [ "$owned" = true ] || [ -n "${LEONAID_TEST_STACK:-}" ]; }; then
    echo "template-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=120 core-postgres api >&2 || true
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

if [ ! -f "$env_file" ]; then
  echo "template-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services="api"
  . "$root/tools/testing/borrow_stack.sh"
else
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
compose up --build --detach --wait --wait-timeout 420 api

fi

compose run --rm --no-deps \
  --user "$host_user_id:$host_group_id" \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo/src:/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/seed/golden.py seed-core \
  /repo/tests/fixtures/golden/v1

compose run --rm --no-deps \
  --user "$host_user_id:$host_group_id" \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo/src:/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/templates/contract.py

echo "template-test: OK: versionierte Templates und Vorjahreskopie bewiesen"
