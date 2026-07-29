#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_OPERATIONS_TEST_PROJECT:-leonaid-poc114-test}
http_port=${LEONAID_OPERATIONS_TEST_PORT:-18134}
https_port=${LEONAID_OPERATIONS_TEST_HTTPS_PORT:-18494}
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
    echo "operations-test: Diagnose der fehlgeschlagenen Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=300 \
      api worker proxy web core-postgres rustfs mailpit twenty-server >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

contract() {
  compose run --rm --no-deps \
    --user "$(id -u):$(id -g)" \
    --env-from-file "$env_file" \
    --env API_BASE_URL=http://api:8000 \
    --env MAIL_TEST_API_URL=http://mailpit:8025/mail \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api tools/operations/contract.py "$@"
}

if [ ! -f "$env_file" ]; then
  echo "operations-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
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
  echo "operations-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api worker

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

contract prepare /proof/sessions.env

compose up --detach --wait --wait-timeout 420 pwa public web proxy

compose stop twenty-server
contract expect-dependency twenty
compose up --detach --wait --wait-timeout 420 twenty-server

compose stop rustfs
contract expect-dependency rustfs
compose up --detach --wait --wait-timeout 180 rustfs

compose stop mailpit
contract expect-dependency mail
compose start mailpit
compose up --detach --wait --wait-timeout 120 mailpit

compose stop worker
contract expect-dependency worker

compose stop mailpit
contract create-failed-mail /proof/state.json

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --entrypoint python \
  worker -m leonaid.entrypoints.worker.outbox \
  --worker-id poc114-failing-mail \
  --max-attempts 1 \
  --base-backoff-seconds 0 \
  run-once >"$proof/worker-failure.log"

contract assert-dead-letter /proof/state.json
compose start mailpit
compose up --detach --wait --wait-timeout 120 mailpit worker

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
  operations.spec.mjs \
  --project=chromium-1440 \
  --output=/tmp/leonaid-operations-results \
  --trace=retain-on-failure \
  --reporter=line

contract assert-recovered /proof/state.json

compose logs --no-color api >"$proof/api.log"
compose logs --no-color worker >"$proof/worker.log"

for dependency in twenty rustfs mail worker; do
  if ! grep -F "\"dependency\":\"$dependency\"" "$proof/api.log" \
    | grep -F '"requestId":"poc114-browser-correlation"' >/dev/null; then
    echo "operations-test: ERROR: Browser-Korrelation zu $dependency fehlt" >&2
    exit 1
  fi
done
if ! grep -F '"event":"http.request.completed"' "$proof/api.log" \
  | grep -F '"requestId":"poc114-browser-correlation"' >/dev/null; then
  echo "operations-test: ERROR: korreliertes Browser-Request-Log fehlt" >&2
  exit 1
fi
if ! grep -F '"event":"outbox.job.dead_lettered"' \
  "$proof/worker-failure.log" >/dev/null; then
  echo "operations-test: ERROR: strukturiertes Dead-Letter-Log fehlt" >&2
  exit 1
fi
if ! grep -F '"event":"outbox.job.completed"' "$proof/worker.log" >/dev/null; then
  echo "operations-test: ERROR: strukturiertes Recovery-Log fehlt" >&2
  exit 1
fi

if grep -E \
  'klara\.kern@|system-admin@|poc114-system-admin-|secureMail|%PDF-' \
  "$proof/api.log" "$proof/worker.log" "$proof/worker-failure.log" \
  >/dev/null; then
  echo "operations-test: ERROR: Logs enthalten PII, Token oder Dokumentbytes" >&2
  exit 1
fi

for screenshot in \
  operations-dead-letter.png operations-recovered.png operations-mobile.png
do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "operations-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done

mkdir -p "$root/.artifacts/poc114"
cp "$proof"/operations-*.png "$root/.artifacts/poc114/"
cp "$proof"/api.log "$proof"/worker.log "$proof"/worker-failure.log \
  "$root/.artifacts/poc114/"

echo "operations-test: OK: korrelierte Logs, Metriken, trennscharfe Ausfälle,"
echo "operations-test:     sicherer UI-Retry und loghygienische Browser-UX bewiesen"
