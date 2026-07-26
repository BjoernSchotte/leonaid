#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"

run_python() {
  docker run --rm \
    -e PYTHONPATH=/workspace/src \
    -e UV_CACHE_DIR=/workspace/.cache/uv \
    -e UV_LINK_MODE=copy \
    -v "$root:/workspace" \
    -w /workspace \
    "$UV_IMAGE" \
    "$@"
}

run_bun() {
  docker run --rm \
    -e BUN_INSTALL_CACHE_DIR=/workspace/.cache/bun \
    -v "$root:/workspace" \
    -w /workspace \
    "$BUN_IMAGE" \
    "$@"
}

run_python uv run --frozen --no-sync ruff check \
  migrations src tests tools/action_admin tools/actions tools/activities \
  tools/activity_feed tools/assignments tools/ci tools/commitments \
  tools/compose/persistence_probe.py tools/core tools/dx tools/identity \
  tools/invitations tools/matching tools/openapi tools/outbox tools/policy \
  tools/public_actions tools/public_orders tools/pwa tools/schema tools/seed \
  tools/sessions tools/templates tools/testkit tools/twenty packages/testkit
run_python uv run --frozen --no-sync ruff format --check \
  migrations src tests tools/action_admin tools/actions tools/activities \
  tools/activity_feed tools/assignments tools/ci tools/commitments \
  tools/compose/persistence_probe.py tools/core tools/dx tools/identity \
  tools/invitations tools/matching tools/openapi tools/outbox tools/policy \
  tools/public_actions tools/public_orders tools/pwa tools/schema tools/seed \
  tools/sessions tools/templates tools/testkit tools/twenty packages/testkit
run_python uv run --frozen --no-sync mypy \
  migrations src tools/action_admin tools/actions tools/activities \
  tools/activity_feed tools/assignments tools/ci tools/commitments \
  tools/compose/persistence_probe.py tools/core tools/dx tools/identity \
  tools/invitations tools/matching tools/openapi tools/outbox tools/policy \
  tools/public_actions tools/public_orders tools/pwa tools/schema tools/seed \
  tools/sessions tools/templates tools/testkit tools/twenty packages/testkit
run_python uv run --frozen --no-sync \
  python tools/openapi/generate.py --root /workspace --check
run_python uv run --frozen --no-sync \
  python tools/openapi/check_frontend.py --root /workspace
run_bun bun run typecheck
run_bun bun node_modules/prettier/bin/prettier.cjs --check \
  .github apps/public apps/pwa apps/web packages/api-client packages/features \
  packages/ui tests/contract tests/e2e package.json playwright.config.mjs \
  .prettierrc.json

echo "ci-lint-types: OK"
