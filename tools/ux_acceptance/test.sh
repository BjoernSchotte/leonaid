#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_UX_TEST_PROJECT:-leonaid-poc102-test}-$suffix
owned=false
http_port=${LEONAID_UX_TEST_PORT:-18122}
https_port=${LEONAID_UX_TEST_HTTPS_PORT:-18482}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
artifact_directory="$root/.artifacts/poc102"
browser_results="$root/.artifacts/ux-acceptance-browser/$project"
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

api_switched=false
restore_api() {
  if [ "$api_switched" = true ]; then
    LEONAID_DISABLED_MODULES= compose up --detach --wait --wait-timeout 420 \
      --no-deps --force-recreate api
    api_switched=false
  fi
}

cleanup() {
  status=$?
  # A borrowed stack must leave with the default module set.
  if [ -n "${LEONAID_TEST_STACK:-}" ] && ! restore_api; then status=1; fi
  if [ "$status" -ne 0 ] && { [ "$owned" = true ] || [ -n "${LEONAID_TEST_STACK:-}" ]; }; then
    echo "ux-acceptance-test: diagnostics for the failed services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=220 \
      api core-postgres pwa web public proxy twenty-server twenty-worker >&2 ||
      true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  if [ "$owned" = true ]; then
    if ! compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    if ! verify_owned_project_removed "$project"; then status=1; fi
    if [ "$status" -eq 0 ]; then echo "test-isolation: $project passed and owned resources were removed"; fi
  fi
  if [ "$status" -eq 0 ]; then rm -rf "$browser_results"; fi
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "ux-acceptance-test: ERROR: .env.local missing; run ./leonaid bootstrap first" >&2
  exit 1
fi

mkdir -p "$browser_results"
chmod 700 "$browser_results"
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
mkdir -p "$browser_results"
chmod 700 "$browser_results"
compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
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
  echo "ux-acceptance-test: ERROR: restricted Twenty key missing" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${project}-api"
fi

compose --profile dev-mail run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/dashboard/contract.py

compose up --detach --wait --wait-timeout 420 public pwa web proxy

# Runs Playwright specs against the proxy; extra arguments go to
# `playwright test`.
run_browser() {
  docker run --rm \
    --network "${project}_edge" \
    --env CI=1 \
    --env HOME=/tmp \
    --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof \
    --env LEONAID_PALETTE_DISABLED_MODULES="${palette_disabled_modules:-}" \
    --volume "$browser_results:/browser-results" \
    --env ANNA_SESSION=poc101-10000000-0000-4000-8000-000000000004-server-session-token-value \
    --env KLARA_SESSION=poc101-10000000-0000-4000-8000-000000000002-server-session-token-value \
    --env FELIX_SESSION=poc101-10000000-0000-4000-8000-000000000003-server-session-token-value \
    --env SIMONE_SESSION=poc101-10000000-0000-4000-8000-000000000001-server-session-token-value \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test \
    --browser=chromium \
    --trace=retain-on-failure \
    --reporter=line \
    "$@"
}

run_browser tests/e2e/ux-acceptance.spec.mjs tests/e2e/command-palette.spec.mjs \
  --output=/browser-results/run

# Review Focus #1: with modules switched off, the palette offers neither
# their navigation nor their search. Only the API reads the switch; it is
# restored afterwards (also on failure, see cleanup).
palette_disabled_modules=tasks,inbox
api_switched=true
LEONAID_DISABLED_MODULES=$palette_disabled_modules \
  compose up --detach --wait --wait-timeout 420 --no-deps --force-recreate api
run_browser tests/e2e/command-palette.spec.mjs \
  --output=/browser-results/disabled-modules
restore_api
palette_disabled_modules=

for report in \
  performance-report.json \
  ux-admin-accessibility.json \
  ux-acquirer-accessibility.json \
  ux-public-accessibility.json; do
  if [ ! -s "$proof/$report" ]; then
    echo "ux-acceptance-test: ERROR: report missing: $report" >&2
    exit 1
  fi
done

for screenshot in \
  ux-admin-desktop.png \
  ux-acquirer-mobile.png \
  ux-public-order-mobile.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "ux-acceptance-test: ERROR: browser evidence missing: $screenshot" >&2
    exit 1
  fi
done

mkdir -p "$artifact_directory"
cp "$proof"/performance-report.json "$artifact_directory/"
cp "$proof"/ux-*.json "$artifact_directory/"
cp "$proof"/ux-*.png "$artifact_directory/"

echo "ux-acceptance-test: OK: admin, acquirer and public,"
echo "ux-acceptance-test:     keyboard, screen reader, 200 %, a11y and performance proven"
