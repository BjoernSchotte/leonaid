#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"

run_python() {
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
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
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -e BUN_INSTALL_CACHE_DIR=/workspace/.cache/bun \
    -v "$root:/workspace" \
    -w /workspace \
    "$BUN_IMAGE" \
    "$@"
}

run_python uv run --frozen --no-sync ruff check \
  tools/testing/phase_test.py tools/testing/ci_fixture.py tools/testing/ci_fixture_test.py tools/testing/seed_fixture.py tools/local_tests_test.py tools/testing/local_stack.py tools/testing/shared_stack.py tools/testing/shared_stack_test.py \
  tools/testing/shared_stack_live.py tools/testing/owned_teardown_live.py tools/surveys/gate.py tools/surveys/gate_test.py tools/testing/module_browser_seed.py tools/testing/run_python_contracts.py
run_python uv run --frozen --no-sync ruff format --check \
  tools/testing/phase_test.py tools/testing/ci_fixture.py tools/testing/ci_fixture_test.py tools/testing/seed_fixture.py tools/local_tests_test.py tools/testing/local_stack.py tools/testing/shared_stack.py tools/testing/shared_stack_test.py \
  tools/testing/shared_stack_live.py tools/testing/owned_teardown_live.py tools/surveys/gate.py tools/surveys/gate_test.py tools/testing/module_browser_seed.py tools/testing/run_python_contracts.py

run_python uv run --frozen --no-sync ruff check \
  migrations src tests tools/action_admin tools/actions tools/activities tools/backup \
  tools/activity_feed tools/assignments tools/ci tools/commitments tools/delivery \
  tools/compose/persistence_probe.py tools/core tools/dashboard tools/dx \
  tools/documents tools/feature_flags tools/golden_journey tools/handoff tools/identity tools/mail_domain tools/mail_relay \
  tools/invitations tools/invoices tools/invoice_delivery tools/invoice_settlements \
  tools/legal_configuration tools/matching tools/openapi tools/operations tools/outbox tools/pilot tools/pilot_alerting \
  tools/pilot_contract tools/pilot_decisions tools/pilot_deployment tools/pilot_import tools/pilot_install tools/pilot_readiness tools/pilot_release tools/release tools/policy tools/storage \
  tools/public_actions tools/public_orders tools/privacy tools/pwa tools/schema tools/seed tools/tasks tools/materials tools/knowledge tools/inbox \
  tools/security tools/sessions tools/templates tools/testkit tools/twenty tools/typst \
  tools/upgrade tools/emdash_spike tools/proxy packages/testkit
run_python uv run --frozen --no-sync ruff format --check \
  migrations src tests tools/action_admin tools/actions tools/activities tools/backup \
  tools/activity_feed tools/assignments tools/ci tools/commitments tools/delivery \
  tools/compose/persistence_probe.py tools/core tools/dashboard tools/dx \
  tools/documents tools/feature_flags tools/golden_journey tools/handoff tools/identity tools/mail_domain tools/mail_relay \
  tools/invitations tools/invoices tools/invoice_delivery tools/invoice_settlements \
  tools/legal_configuration tools/matching tools/openapi tools/operations tools/outbox tools/pilot tools/pilot_alerting \
  tools/pilot_contract tools/pilot_decisions tools/pilot_deployment tools/pilot_import tools/pilot_install tools/pilot_readiness tools/pilot_release tools/release tools/policy tools/storage \
  tools/public_actions tools/public_orders tools/privacy tools/pwa tools/schema tools/seed tools/tasks tools/materials tools/knowledge tools/inbox \
  tools/security tools/sessions tools/templates tools/testkit tools/twenty tools/typst \
  tools/upgrade tools/emdash_spike tools/proxy packages/testkit
run_python uv run --frozen --no-sync mypy \
  migrations src tools/action_admin tools/actions tools/activities tools/backup \
  tools/activity_feed tools/assignments tools/ci tools/commitments tools/delivery \
  tools/compose/persistence_probe.py tools/core tools/dashboard tools/dx \
  tools/documents tools/feature_flags tools/golden_journey tools/handoff tools/identity tools/mail_domain tools/mail_relay \
  tools/invitations tools/invoices tools/invoice_delivery tools/invoice_settlements \
  tools/legal_configuration tools/matching tools/openapi tools/operations tools/outbox tools/pilot tools/pilot_alerting \
  tools/pilot_contract tools/pilot_decisions tools/pilot_deployment tools/pilot_import tools/pilot_install tools/pilot_readiness tools/pilot_release tools/release tools/policy tools/storage \
  tools/public_actions tools/public_orders tools/privacy tools/pwa tools/schema tools/seed tools/tasks tools/materials tools/knowledge tools/inbox \
  tools/security tools/sessions tools/templates tools/testkit tools/twenty tools/typst \
  tools/upgrade tools/emdash_spike tools/proxy packages/testkit
run_python uv run --frozen --no-sync \
  python tools/openapi/generate.py --root /workspace --check
run_python uv run --frozen --no-sync \
  python tools/openapi/check_frontend.py --root /workspace
docker run --rm \
  -v "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/handoff/check.py /workspace
# PR/queue tier selection, aggregate gates, flake tally, infra-retry allowlist.
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/select_suites_test.py /workspace
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/gate_test.py
# Merge conflict markers.
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/conflict_markers_test.py
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/conflict_markers.py /workspace
# Browser specs scan through tests/e2e/axe.mjs (no direct AxeBuilder).
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/axe_helper_test.py
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/axe_helper.py /workspace
# Leitsystem only: no Hugeicons, Base UI or old token aliases.
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/legacy_ui_test.py
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/legacy_ui.py /workspace
# Core one-off user containers.
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/core_oneoff_user_test.py /workspace
docker run --rm --network none \
  -v "$root:/workspace:ro" "$PYTHON_IMAGE" \
  python /workspace/tools/ci/core_oneoff_user.py /workspace
# Generated Caddyfiles: drift, adapt/validate with the pinned Caddy, and the
# host routing table of specs/multi-domain proven against a running Caddy.
/bin/sh "$root/tools/proxy/validate-caddyfiles.sh" "$root"
/bin/sh "$root/tools/proxy/routing-test.sh" "$root"
run_bun bun run typecheck
# Leitsystem token contrast (WCAG targets in light and dark, all zones).
run_bun bun run test:ui
# PWA navigation and the column query rewrite of the PWA build.
run_bun bun run test:pwa
# Legal-notice cache of the public pages (footer and /impressum).
run_bun bun run test:public
# Admin/site origins and the Live View URL of the campaign site.
run_bun bun run test:campaign-site
run_bun bun node_modules/prettier/bin/prettier.cjs --check \
  .github apps/campaign-site apps/public apps/pwa apps/web packages/api-client packages/features \
  tools/emdash_spike/*.mjs \
  packages/ui tests/contract tests/e2e package.json playwright.config.mjs \
  .prettierrc.json

echo "ci-lint-types: OK"
