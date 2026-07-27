#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_DASHBOARD_TEST_PROJECT:-leonaid-poc101-test}
http_port=${LEONAID_DASHBOARD_TEST_PORT:-18121}
https_port=${LEONAID_DASHBOARD_TEST_HTTPS_PORT:-18481}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
artifact_directory="$root/.artifacts/poc101"
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
    mkdir -p "$artifact_directory/failures"
    if [ -d "$proof/test-results" ]; then
      cp -R "$proof/test-results/." "$artifact_directory/failures/"
    fi
    echo "dashboard-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=220 \
      api core-postgres pwa web proxy twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "dashboard-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api public pwa web
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
  echo "dashboard-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
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
  api tools/dashboard/contract.py

compose up --detach --wait --wait-timeout 420 public pwa web proxy

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env ANNA_SESSION=poc101-10000000-0000-4000-8000-000000000004-server-session-token-value \
  --env KLARA_SESSION=poc101-10000000-0000-4000-8000-000000000002-server-session-token-value \
  --env FELIX_SESSION=poc101-10000000-0000-4000-8000-000000000003-server-session-token-value \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/dashboard.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

for screenshot in \
  dashboard-acquirer-mobile.png \
  dashboard-admin-desktop.png \
  dashboard-empty-desktop.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "dashboard-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done

mkdir -p "$artifact_directory"
cp "$proof"/dashboard-*.png "$artifact_directory/"

echo "dashboard-test: OK: Golden-Kennzahlen gegen echte SQL-Aggregate,"
echo "dashboard-test:     Rollen, Drilldowns, Leersicht und A11y bewiesen"
