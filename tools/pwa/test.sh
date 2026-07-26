#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_PWA_TEST_PROJECT:-leonaid-poc062-test}
http_port=${LEONAID_PWA_TEST_PORT:-18095}
https_port=${LEONAID_PWA_TEST_HTTPS_PORT:-18455}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
proof=$(mktemp -d)
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
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "pwa-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=160 \
      api core-postgres twenty-server twenty-worker pwa proxy >&2 || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "pwa-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api pwa
compose up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker

compose run --rm --no-deps \
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
  echo "pwa-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

mkdir -p "$proof/pdfs"
for source in "$fixture"/documents/KT26-*.typ; do
  filename=$(basename "$source" .typ)
  docker run --rm \
    --volume "$fixture/documents:/input:ro" \
    --volume "$proof/pdfs:/output" \
    "$TYPST_IMAGE" \
    compile \
    --creation-timestamp 1782864000 \
    --jobs 1 \
    "/input/$filename.typ" \
    "/output/$filename.pdf"
done

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
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env ANNA_SESSION="$anna_session" \
  --env GESA_SESSION="$gesa_session" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/pwa.config.mjs \
  pwa.spec.mjs \
  --output=/proof/test-results-matrix \
  --reporter=line

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env ANNA_SESSION="$anna_session" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/pwa-audit.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results-audit \
  --reporter=line

compose stop twenty-server

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env ANNA_SESSION="$anna_session" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/pwa-error.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results-error \
  --reporter=line

for browser in chromium firefox webkit; do
  for width in 390 768 1440; do
    screenshot="$proof/pwa-list-$browser-$width.png"
    if [ ! -s "$screenshot" ]; then
      echo "pwa-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
      exit 1
    fi
  done
done
for screenshot in \
  pwa-empty-chromium-390.png \
  pwa-update-chromium.png \
  pwa-offline-chromium.png \
  pwa-error-chromium-390.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "pwa-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done

mkdir -p "$root/.artifacts/poc062"
cp "$proof"/pwa-*.png "$root/.artifacts/poc062/"

echo "pwa-test: OK: PWA, reale Sichtgrenzen, Kontakte, 9 Browser/Viewports,"
echo "pwa-test:     A11y, Textskalierung, Touch, Offline, Update, Leer- und Ausfallzustand bewiesen"
