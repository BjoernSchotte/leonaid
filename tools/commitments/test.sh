#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_COMMITMENT_TEST_PROJECT:-leonaid-poc081-test}
http_port=${LEONAID_COMMITMENT_TEST_PORT:-18096}
https_port=${LEONAID_COMMITMENT_TEST_HTTPS_PORT:-18456}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
proof=$(mktemp -d)
integration_key=""
anna_session="poc080-10000000-0000-4000-8000-000000000004-server-session-token-value"
klara_session="poc080-10000000-0000-4000-8000-000000000002-server-session-token-value"

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
    echo "commitment-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=160 \
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
  echo "commitment-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api pwa web
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
  echo "commitment-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
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
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/commitments/contract.py

compose up --detach --wait --wait-timeout 420 pwa web proxy

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env LEONAID_E2E_PROOF_PATH=/proof/poc081-created.json \
  --env ANNA_SESSION="$anna_session" \
  --env KLARA_SESSION="$klara_session" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/pwa.config.mjs \
  commitments.spec.mjs \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --env UI_PROOF_PATH=/proof/poc081-created.json \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/commitments/verify_ui.py

for screenshot in \
  commitment-capture-mobile.png \
  commitment-success-mobile.png \
  commitment-admin-desktop.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "commitment-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done
for browser in chromium firefox webkit; do
  for width in 390 768 1440; do
    screenshot="$proof/commitment-capture-$browser-$width.png"
    if [ ! -s "$screenshot" ]; then
      echo "commitment-test: ERROR: Browsermatrix fehlt: $screenshot" >&2
      exit 1
    fi
  done
done

mkdir -p "$root/.artifacts/poc081"
cp "$proof"/commitment-*.png "$root/.artifacts/poc081/"
cp "$proof/poc081-created.json" "$root/.artifacts/poc081/"

echo "commitment-test: OK: Serververtrag, Browsererfassung, Admin-Sicht,"
echo "commitment-test:     Golden-Summen und 9 Browser/Viewports real bewiesen"
