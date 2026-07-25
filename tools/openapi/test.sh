#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(CDPATH= cd -- "$root" && pwd)
. "$root/infra/locks/images.env"
project=leonaid-poc023-test
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
temporary=$(mktemp -d)

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$temporary"
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

cleanup
compose build api
compose up --detach --wait --wait-timeout 420 api

docker run --rm \
  --network "${project}_edge" \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$BUN_IMAGE" \
  bun tests/contract/api_client.ts

echo "poc023-test: OK: deterministische Generierung, Boundary, Typen und Realvertrag bewiesen"
