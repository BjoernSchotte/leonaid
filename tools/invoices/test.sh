#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_INVOICE_TEST_PROJECT:-leonaid-poc090-test}-$suffix
owned=false
http_port=${LEONAID_INVOICE_TEST_PORT:-18110}
https_port=${LEONAID_INVOICE_TEST_HTTPS_PORT:-18470}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
integration_key=""

compose() {
  LEONAID_HTTP_PORT="$http_port" \
    LEONAID_HTTPS_PORT="$https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
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
    echo "invoice-test: diagnostics for the failed real services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=180 \
      api core-postgres twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
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

if [ ! -f "$env_file" ]; then
  echo "invoice-test: ERROR: .env.local is missing; run ./leonaid bootstrap first" >&2
  exit 1
fi

if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services="api twenty-worker mailpit"
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
build_shared_images api worker public pwa web
compose up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/twenty/provision.py apply \
  --token-output /proof/integration.env

integration_key=$(sed -n 's/^TWENTY_INTEGRATION_API_KEY=//p' \
  "$proof/integration.env")
if [ "${#integration_key}" -lt 32 ]; then
  echo "invoice-test: ERROR: restricted Twenty key is missing" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${project}-api"

fi

golden_seed

compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/invoices/contract.py

# The server contract changes the real CRM address on purpose. So the
# golden state is fully reset before the browser proof.
golden_seed

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --env SESSION_OUTPUT=/proof/sessions.env \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/invoices/browser_setup.py

session_mode=$(stat -c '%a' "$proof/sessions.env" 2>/dev/null || \
  stat -f '%Lp' "$proof/sessions.env")
if [ "$session_mode" != "600" ]; then
  echo "invoice-test: ERROR: browser sessions are not restricted to mode 600" >&2
  exit 1
fi

compose --profile dev-mail up --detach --wait --wait-timeout 420 \
  worker pwa web proxy

# The bulk fault proof runs after the main proof: it relies on its invoice
# numbers and seeded orders, and its source is pinned in
# tools/ci/reviewed_network_faults.json.
for spec in invoices.spec.mjs invoices-bulk-faults.spec.mjs delivery-board.spec.mjs; do
  docker run --rm \
    --network "${project}_edge" \
    --env CI=1 \
    --env HOME=/tmp \
    --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_MAILPIT_URL=http://mailpit:8025/mail \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof \
    --env-file "$proof/sessions.env" \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test \
    --config=tests/e2e/pwa.config.mjs \
    "$spec" \
    --project=chromium-1440 \
    --output="/proof/test-results/${spec%.spec.mjs}" \
    --trace=retain-on-failure \
    --reporter=line
done

for screenshot in \
  invoice-review-desktop.png \
  invoice-delivery-completion-mobile.png \
  invoice-ledger-desktop.png \
  invoice-ledger-dark.png \
  invoice-finance-mobile.png \
  invoice-bulk-release-desktop.png \
  invoice-bulk-release-result.png \
  invoice-bulk-release-retry.png \
  invoice-bulk-release-refused.png \
  delivery-board-desktop.png \
  delivery-board-driver-mobile.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "invoice-test: ERROR: browser proof is missing: $screenshot" >&2
    exit 1
  fi
done

mkdir -p "$root/.artifacts/poc090"
cp "$proof"/invoice-*.png "$proof"/delivery-board-*.png "$root/.artifacts/poc090/"

echo "invoice-test: OK: server contract, fresh login, invoice issuing,"
echo "invoice-test:     finance reader view and real Twenty snapshots proven"
