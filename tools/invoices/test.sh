#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_INVOICE_TEST_PROJECT:-leonaid-poc090-test}
http_port=${LEONAID_INVOICE_TEST_PORT:-18110}
https_port=${LEONAID_INVOICE_TEST_HTTPS_PORT:-18470}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
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
    echo "invoice-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=180 \
      api core-postgres twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "invoice-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api worker public pwa web
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
  echo "invoice-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${project}-api"

compose --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/invoices/contract.py

# Der Serververtrag ändert die reale CRM-Adresse absichtlich. Für den
# Browsernachweis wird der Golden-Stand deshalb vollständig zurückgesetzt.
compose --profile dev-mail run --rm --no-deps \
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
  --env PYTHONPATH=/repo:/workspace/src \
  --env SESSION_OUTPUT=/proof/sessions.env \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/invoices/browser_setup.py

session_mode=$(stat -f '%Lp' "$proof/sessions.env" 2>/dev/null || \
  stat -c '%a' "$proof/sessions.env")
if [ "$session_mode" != "600" ]; then
  echo "invoice-test: ERROR: Browser-Sitzungen sind nicht auf Modus 600 begrenzt" >&2
  exit 1
fi

compose --profile dev-mail up --detach --wait --wait-timeout 420 \
  worker pwa web proxy

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
  invoices.spec.mjs \
  --project=chromium-1440 \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

for screenshot in \
  invoice-review-desktop.png \
  invoice-ledger-desktop.png \
  invoice-ledger-dark.png \
  invoice-finance-mobile.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "invoice-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done

mkdir -p "$root/.artifacts/poc090"
cp "$proof"/invoice-*.png "$root/.artifacts/poc090/"

echo "invoice-test: OK: Serververtrag, Fresh Login, Rechnungsfreigabe,"
echo "invoice-test:     Finanz-Lesesicht und echte Twenty-Snapshots bewiesen"
