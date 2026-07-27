#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_FEATURE_FLAG_TEST_PROJECT:-leonaid-poc096-test}
http_port=${LEONAID_FEATURE_FLAG_TEST_PORT:-18116}
https_port=${LEONAID_FEATURE_FLAG_TEST_HTTPS_PORT:-18476}
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
    echo "feature-flag-test: Diagnose der fehlgeschlagenen Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=260 \
      api core-postgres web proxy twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "feature-flag-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api public pwa web
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
  echo "feature-flag-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
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
  api tools/feature_flags/contract.py prepare /proof/sessions.env

session_mode=$(stat -f '%Lp' "$proof/sessions.env" 2>/dev/null || \
  stat -c '%a' "$proof/sessions.env")
if [ "$session_mode" != "600" ]; then
  echo "feature-flag-test: ERROR: Browser-Sitzungen sind nicht Modus 600" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 pwa public web proxy

https_ready=false
for _attempt in $(seq 1 90); do
  if compose exec -T proxy wget \
    --no-check-certificate \
    --quiet \
    --output-document=- \
    https://proxy:8443/_health >/dev/null 2>&1; then
    https_ready=true
    break
  fi
  sleep 1
done
if [ "$https_ready" != "true" ]; then
  echo "feature-flag-test: ERROR: HTTPS-Proxy wurde nicht bereit" >&2
  exit 1
fi

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
  feature-flags.spec.mjs \
  --project=chromium-1440 \
  --output=/tmp/leonaid-feature-flag-results \
  --trace=retain-on-failure \
  --reporter=line

for screenshot in feature-flags-desktop.png feature-flags-mobile.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "feature-flag-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done

compose restart api
compose up --detach --wait --wait-timeout 120 api

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/feature_flags/contract.py assert

mkdir -p "$root/.artifacts/poc096"
cp "$proof"/feature-flags-*.png "$root/.artifacts/poc096/"

echo "feature-flag-test: OK: OpenFeature Python/React, Persistenz, Audit,"
echo "feature-flag-test:     Fresh-Login, RBAC und Browser-UX bewiesen"
