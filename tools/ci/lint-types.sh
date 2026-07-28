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
  migrations src tests tools/action_admin tools/actions tools/activities tools/backup \
  tools/activity_feed tools/assignments tools/ci tools/commitments \
  tools/compose/persistence_probe.py tools/core tools/dashboard tools/dx \
  tools/documents tools/feature_flags tools/golden_journey tools/handoff tools/identity \
  tools/invitations tools/invoices tools/invoice_delivery tools/invoice_settlements \
  tools/matching tools/openapi tools/operations tools/outbox tools/pilot \
  tools/pilot_contract tools/pilot_decisions tools/policy tools/storage \
  tools/public_actions tools/public_orders tools/privacy tools/pwa tools/schema tools/seed \
  tools/security tools/sessions tools/templates tools/testkit tools/twenty tools/typst \
  tools/upgrade packages/testkit
run_python uv run --frozen --no-sync ruff format --check \
  migrations src tests tools/action_admin tools/actions tools/activities tools/backup \
  tools/activity_feed tools/assignments tools/ci tools/commitments \
  tools/compose/persistence_probe.py tools/core tools/dashboard tools/dx \
  tools/documents tools/feature_flags tools/golden_journey tools/handoff tools/identity \
  tools/invitations tools/invoices tools/invoice_delivery tools/invoice_settlements \
  tools/matching tools/openapi tools/operations tools/outbox tools/pilot \
  tools/pilot_contract tools/pilot_decisions tools/policy tools/storage \
  tools/public_actions tools/public_orders tools/privacy tools/pwa tools/schema tools/seed \
  tools/security tools/sessions tools/templates tools/testkit tools/twenty tools/typst \
  tools/upgrade packages/testkit
run_python uv run --frozen --no-sync mypy \
  migrations src tools/action_admin tools/actions tools/activities tools/backup \
  tools/activity_feed tools/assignments tools/ci tools/commitments \
  tools/compose/persistence_probe.py tools/core tools/dashboard tools/dx \
  tools/documents tools/feature_flags tools/golden_journey tools/handoff tools/identity \
  tools/invitations tools/invoices tools/invoice_delivery tools/invoice_settlements \
  tools/matching tools/openapi tools/operations tools/outbox tools/pilot \
  tools/pilot_contract tools/pilot_decisions tools/policy tools/storage \
  tools/public_actions tools/public_orders tools/privacy tools/pwa tools/schema tools/seed \
  tools/security tools/sessions tools/templates tools/testkit tools/twenty tools/typst \
  tools/upgrade packages/testkit
run_python uv run --frozen --no-sync \
  python tools/openapi/generate.py --root /workspace --check
run_python uv run --frozen --no-sync \
  python tools/openapi/check_frontend.py --root /workspace
docker run --rm \
  -v "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/handoff/check.py /workspace
run_bun bun run typecheck
run_bun bun node_modules/prettier/bin/prettier.cjs --check \
  .github apps/public apps/pwa apps/web packages/api-client packages/features \
  packages/ui tests/contract tests/e2e package.json playwright.config.mjs \
  .prettierrc.json

echo "ci-lint-types: OK"
