#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(CDPATH= cd -- "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
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
    if ! verify_owned_project_removed "$project"; then status=1; fi
    if [ "$status" -eq 0 ]; then echo "test-isolation: $project passed and owned resources were removed"; fi
  fi
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

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

# The live contract needs only a running API; a leaf of the shared feature
# fixture (./leonaid test-integration) borrows its restored stack instead of
# a cold Twenty installation. Standalone runs (CI api-contract) own a stack.
if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services=api
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
  build_shared_images api
  compose up --detach --wait --wait-timeout 420 api
fi

docker run --rm \
  --network "${project}_edge" \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$BUN_IMAGE" \
  bun tests/contract/api_client.ts

echo "poc023-test: OK: deterministic generation, boundary, types and real contract proven"
