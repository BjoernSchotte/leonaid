#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_PWA_TEST_PROJECT:-leonaid-poc062-test}-$suffix
owned=false
http_port=${LEONAID_PWA_TEST_PORT:-18095}
https_port=${LEONAID_PWA_TEST_HTTPS_PORT:-18455}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
integration_key=""
anna_session="poc062-10000000-0000-4000-8000-000000000004-server-session-token-value"
gesa_session="poc062-10000000-0000-4000-8000-000000000008-server-session-token-value"

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
    echo "pwa-test: diagnostics for the failed real services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=160 \
      api core-postgres twenty-server twenty-worker pwa proxy >&2 || true
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
  echo "pwa-test: ERROR: .env.local is missing; run ./leonaid bootstrap first" >&2
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
build_shared_images api pwa
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
  echo "pwa-test: ERROR: restricted Twenty key is missing" >&2
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
  --env-from-file "$proof/integration.env" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/pwa/contract.py

compose up --detach --wait --wait-timeout 420 pwa proxy

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env ANNA_SESSION="$anna_session" \
  --env GESA_SESSION="$gesa_session" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/pwa.config.mjs \
  pwa.spec.mjs \
  --output=/proof/test-results-matrix \
  --trace=retain-on-failure \
  --reporter=line

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env ANNA_SESSION="$anna_session" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/pwa-audit.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results-audit \
  --trace=retain-on-failure \
  --reporter=line

# Offline queue (specs/pwa-offline-queue §16): the flag is switched on only
# for its own specs; every other PWA spec proves the copy without it.
offline_flag() {
  printf "UPDATE feature_flag SET enabled = %s, revision = revision + 1 WHERE key = 'pwa.offline_queue';\n" "$1" |
    compose exec -T core-postgres sh -ec \
      'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}
offline_flag true
for browser in chromium webkit; do
  docker run --rm \
    --network "${project}_edge" \
    --env CI=1 \
    --env HOME=/tmp \
    --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof \
    --env ANNA_SESSION="$anna_session" \
    --env LEONAID_E2E_BROWSER="$browser" \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test \
    tests/e2e/pwa-offline.spec.mjs \
    tests/e2e/pwa-offline-queue.spec.mjs \
    --browser="$browser" \
    --output="/proof/test-results-offline-$browser" \
    --trace=retain-on-failure \
    --reporter=line
done
offline_flag false

compose stop twenty-server

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env ANNA_SESSION="$anna_session" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/pwa-error.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results-error \
  --trace=retain-on-failure \
  --reporter=line

for browser in chromium firefox webkit; do
  for width in 390 768 1440; do
    screenshot="$proof/pwa-list-$browser-$width.png"
    if [ ! -s "$screenshot" ]; then
      echo "pwa-test: ERROR: browser evidence is missing: $screenshot" >&2
      exit 1
    fi
  done
done
for screenshot in \
  pwa-empty-chromium-390.png \
  pwa-update-chromium.png \
  pwa-offline-chromium.png \
  pwa-offline-start-chromium.png \
  pwa-offline-start-webkit.png \
  pwa-offline-queue-chromium.png \
  pwa-offline-queue-webkit.png \
  pwa-error-chromium-390.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "pwa-test: ERROR: browser evidence is missing: $screenshot" >&2
    exit 1
  fi
done

mkdir -p "$root/.artifacts/poc062"
cp "$proof"/pwa-*.png "$root/.artifacts/poc062/"

echo "pwa-test: OK: PWA, real visibility boundaries, contacts, 9 browsers/viewports,"
echo "pwa-test:     a11y, text scaling, touch, offline, update, empty and outage states proven"
