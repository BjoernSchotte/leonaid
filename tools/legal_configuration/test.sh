#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_LEGAL_TEST_PROJECT:-leonaid-pilot044-test}
http_port=${LEONAID_LEGAL_TEST_PORT:-18124}
https_port=${LEONAID_LEGAL_TEST_HTTPS_PORT:-18484}
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
    echo "legal-configuration-test: Diagnose:" >&2
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
  echo "legal-configuration-test: ERROR: .env.local fehlt" >&2
  exit 1
fi

docker run --rm \
  --env HOME=/tmp \
  --env UV_CACHE_DIR=/tmp/uv-cache \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$UV_IMAGE" \
  uv run --frozen --no-sync \
  pytest -p no:cacheprovider tests/unit/test_legal_configuration.py --quiet

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api public pwa web
if ! compose --profile dev-mail up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker; then
  echo "legal-configuration-test: Twenty-Start wird einmal wiederholt"
  compose --profile dev-mail up --detach --wait --wait-timeout 420 \
    core-postgres rustfs mailpit twenty-server twenty-worker
fi

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
  echo "legal-configuration-test: ERROR: Twenty-Key fehlt" >&2
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
  api tools/legal_configuration/contract.py prepare \
  --sessions /proof/sessions.env

compose up --detach --wait --wait-timeout 420 pwa public web proxy

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
  legal-configuration.spec.mjs \
  --project=chromium-1440 \
  --output=/tmp/leonaid-legal-results \
  --trace=retain-on-failure \
  --reporter=line

for screenshot in legal-draft-desktop.png legal-active-mobile.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "legal-configuration-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/legal_configuration/contract.py assert

mkdir -p "$root/.artifacts/pilot044"
cp "$proof"/legal-*.png "$root/.artifacts/pilot044/"

echo "legal-configuration-test: OK: reale PostgreSQL-Versionierung,"
echo "legal-configuration-test:     Vier-Augen-Aktivierung und Browser-UX bewiesen"
