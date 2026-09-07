#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(CDPATH= cd -- "$root" && pwd)
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc023-test-$suffix
owned=false
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
temporary=$(mktemp -d)
proof="$temporary"
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
  -e PYTHONPATH=/workspace/src \
  -e UV_CACHE_DIR=/tmp/uv-cache \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$UV_IMAGE" \
  uv run --frozen --no-sync \
  python tools/openapi/generate.py --root /workspace --check

docker run --rm \
  --user "$host_user_id:$host_group_id" \
  -e PYTHONPATH=/workspace/src \
  -e UV_CACHE_DIR=/tmp/uv-cache \
  -v "$root:/workspace:ro" \
  -v "$temporary:/output" \
  -w /workspace \
  "$UV_IMAGE" \
  uv run --frozen --no-sync \
  python tools/openapi/generate.py --root /output

cmp \
  "$root/packages/api-client/openapi.json" \
  "$temporary/packages/api-client/openapi.json"
cmp \
  "$root/packages/api-client/src/generated.ts" \
  "$temporary/packages/api-client/src/generated.ts"

docker run --rm \
  -e PYTHONPATH=/workspace/src \
  -e UV_CACHE_DIR=/tmp/uv-cache \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$UV_IMAGE" \
  uv run --frozen --no-sync \
  python tools/openapi/check_frontend.py --root /workspace

docker run --rm \
  -e PYTHONPATH=/workspace/src \
  -e UV_CACHE_DIR=/tmp/uv-cache \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$UV_IMAGE" \
  uv run --frozen --no-sync \
  python tools/openapi/breaking.py \
  packages/api-client/openapi.json \
  packages/api-client/openapi.json \
  specs/leonaid-poc/openapi-breaking-approvals.json

docker run --rm \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$BUN_IMAGE" \
  bun run typecheck:api-client
docker run --rm \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$BUN_IMAGE" \
  bun node_modules/prettier/bin/prettier.cjs --check \
  packages/api-client tests/contract package.json

compose build api
compose up --detach --wait --wait-timeout 420 api

docker run --rm \
  --network "${project}_edge" \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$BUN_IMAGE" \
  bun tests/contract/api_client.ts

echo "poc023-test: OK: deterministische Generierung, Boundary, Typen und Realvertrag bewiesen"
