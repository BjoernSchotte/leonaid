#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc021-test-$suffix
owned=false
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
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
    --file "$isolation_file" \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "poc021-test: Diagnose der realen Core-Datenbank:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=100 core-postgres >&2 || true
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
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

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

docker run --rm \
  -v "$root:/repo:ro" \
  docker.io/library/python:3.13.13-slim-trixie@sha256:aa938a849bcb82dce8f49480f056ab82bf5c1c3ebc294f0430f37b6820e7f286 \
  python /repo/tools/schema/check_migrations.py /repo/migrations/versions

echo "poc021-test: migriert eine vollständig leere PostgreSQL-Instanz bis Head"
compose build api
compose up --detach --wait --wait-timeout 120 core-postgres
compose run --rm --no-deps --entrypoint alembic api upgrade head

if [ "${2:-full}" = "code-rollback" ]; then
  # Pinned predecessors of registration, Tasks, and Inbox. No checkout mutation.
  for revision in 4d05276c5b74932461926e86c8a4fdbaa5f192b6 07d100883c418370afa662b41aef0dfc8743335d b46f46223c9ddb3d16a02e13875609febcc63eed; do
    mkdir "$proof/$revision"
    git -C "$root" archive --format=tar "$revision" src >"$proof/source.tar"
    tar -xf "$proof/source.tar" -C "$proof/$revision"
    echo "code-rollback: testing $revision against the expanded schema"
    compose run --rm --no-deps \
      --volume "$proof/$revision:/old:ro" \
      --volume "$root/tools/schema/code_rollback.py:/proof.py:ro" \
      --env PYTHONPATH=/old/src --env ROLLBACK_SOURCE=/old/src \
      --entrypoint python api /proof.py
  done
  echo "code-rollback: PASS: older API startup and identity on current schema; new-job drain remains separate"
  exit 0
fi
compose up --detach --wait --wait-timeout 120 rustfs
compose run --rm --no-deps \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/testing/run_python_contracts.py \
    /repo/tools/schema/smoke.py \
    /repo/tools/tasks/schema_contract.py \
    /repo/tools/knowledge/schema_contract.py \
    /repo/tools/materials/schema_contract.py \
    /repo/tools/inbox/schema_contract.py \
    /repo/tools/inbox/submission_contract.py \
    /repo/tools/inbox/case_contract.py \
    /repo/tools/inbox/http_contract.py \
    /repo/tools/inbox/public_contract.py \
    /repo/tools/inbox/task_contract.py \
    /repo/tools/inbox/material_contract.py \
    /repo/tools/materials/service_contract.py \
    /repo/tools/materials/member_contract.py \
    /repo/tools/materials/action_contract.py \
    /repo/tools/materials/cleanup_contract.py \
    /repo/tools/materials/http_contract.py \
    /repo/tools/knowledge/service_contract.py \
    /repo/tools/knowledge/material_contract.py \
    /repo/tools/knowledge/http_contract.py \
    /repo/tools/knowledge/action_contract.py \
    /repo/tools/knowledge/task_contract.py \
    /repo/tools/knowledge/member_contract.py \
    /repo/tools/tasks/service_contract.py \
    /repo/tools/tasks/planning_contract.py \
    /repo/tools/tasks/ordering_contract.py \
    /repo/tools/tasks/http_contract.py \
    /repo/tools/tasks/action_contract.py

echo "poc021-test: migriert den versionierten Vorgänger-Snapshot samt Daten"
compose --profile '*' down --volumes --remove-orphans
compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
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
