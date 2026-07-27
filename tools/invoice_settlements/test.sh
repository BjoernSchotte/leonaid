#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_INVOICE_SETTLEMENT_TEST_PROJECT:-leonaid-poc095-test}
http_port=${LEONAID_INVOICE_SETTLEMENT_TEST_PORT:-18115}
https_port=${LEONAID_INVOICE_SETTLEMENT_TEST_HTTPS_PORT:-18475}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
integration_key=""

compose() {
  LEONAID_HTTP_PORT="$http_port" \
    LEONAID_HTTPS_PORT="$https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "invoice-settlement-test: Diagnose der fehlgeschlagenen Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=260 \
      api core-postgres rustfs worker pwa web proxy \
      twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "invoice-settlement-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api worker public pwa web
compose --profile dev-mail up --detach --wait --wait-timeout 420 \
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
  echo "invoice-settlement-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${project}-api"

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/invoice_settlements/contract.py prepare \
  /proof/state.json /proof/sessions.env

compose run --rm --no-deps \
  worker python -m leonaid.entrypoints.worker.outbox \
  --worker-id poc095-render \
  --max-attempts 5 \
  --base-backoff-seconds 0 \
  run-until-idle

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/invoice_settlements/contract.py capture /proof/state.json

session_mode=$(stat -c '%a' "$proof/sessions.env" 2>/dev/null || \
  stat -f '%Lp' "$proof/sessions.env")
if [ "$session_mode" != "600" ]; then
  echo "invoice-settlement-test: ERROR: Browser-Sitzungen sind nicht Modus 600" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 pwa web proxy

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env-file "$proof/sessions.env" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/pwa.config.mjs \
  invoice-settlements.spec.mjs \
  --project=chromium-1440 \
  --output=/tmp/leonaid-invoice-settlement-results \
  --trace=retain-on-failure \
  --reporter=line

for screenshot in \
  invoice-open-and-paid.png \
  invoice-payment-recorded.png \
  invoice-cancellation.png \
  invoice-finance-readonly-mobile.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "invoice-settlement-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/invoice_settlements/contract.py assert /proof/state.json

mkdir -p "$root/.artifacts/poc095"
cp "$proof"/invoice-*.png "$root/.artifacts/poc095/"

echo "invoice-settlement-test: OK: Rollen, Vollzahlung, Storno, Audit,"
echo "invoice-settlement-test:     Browser-UX und unverändertes Typst-PDF bewiesen"
