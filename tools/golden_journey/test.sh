#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_GOLDEN_JOURNEY_PROJECT:-leonaid-poc122-test}
http_port=${LEONAID_GOLDEN_JOURNEY_PORT:-18142}
https_port=${LEONAID_GOLDEN_JOURNEY_HTTPS_PORT:-18502}
compose_file="$root/infra/compose/compose.yml"
network_overlay="$root/infra/upgrade/compose.rollback-network.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
integration_key=""
journey_generation=0
token_filename=""
LEONAID_CI_ARTIFACT_DIR=${LEONAID_CI_ARTIFACT_DIR:-.artifacts/failures/poc122}
export LEONAID_CI_ARTIFACT_DIR

compose() {
  LEONAID_HTTP_PORT="$http_port" \
    LEONAID_HTTPS_PORT="$https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$network_overlay" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "golden-journey: Diagnose der fehlgeschlagenen Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=400 \
      api worker public pwa web proxy core-postgres rustfs mailpit \
      twenty-server twenty-worker >&2 || true
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
    --env MAILPIT_API_URL=http://mailpit:8025/mail \
    --env TWENTY_BASE_URL=http://twenty-server:3000 \
    --env TWENTY_INTEGRATION_API_KEY="$integration_key" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api tools/golden_journey/contract.py "$@"
}

start_golden() {
  integration_key=""
  journey_generation=$((journey_generation + 1))
  token_filename="integration-$journey_generation.env"
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
    --token-output "/proof/$token_filename"

  integration_key=$(sed -n 's/^TWENTY_INTEGRATION_API_KEY=//p' \
    "$proof/$token_filename")
  if [ "${#integration_key}" -lt 32 ]; then
    echo "golden-journey: ERROR: eingeschränkter Twenty-Key fehlt" >&2
    exit 1
  fi

  compose run --rm --no-deps \
    --env-from-file "$env_file" \
    --env PYTHONPATH=/repo:/workspace/src \
    --env TWENTY_BASE_URL=http://twenty-server:3000 \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof:ro" \
    --workdir /repo \
    --entrypoint python \
    api /repo/tools/twenty/provision.py verify-key \
    --token-file "/proof/$token_filename"

  compose up --detach --force-recreate --wait --wait-timeout 420 api
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
  compose --profile dev-mail up --detach --wait --wait-timeout 420 \
    worker public pwa web proxy
}

run_round() {
  round_name=$1
  artifact_path=$2
  summary_path=$3
  normalized_path=$4
  mkdir -p "$artifact_path"
  contract prepare-sessions "$round_name" "/proof/sessions-$round_name.env"
  session_mode=$(stat -f '%Lp' "$proof/sessions-$round_name.env" 2>/dev/null || \
    stat -c '%a' "$proof/sessions-$round_name.env")
  if [ "$session_mode" != "600" ]; then
    echo "golden-journey: ERROR: Sitzungsdatei ist nicht Modus 600" >&2
    exit 1
  fi

  docker run --rm \
    --network "${project}_edge" \
    --env CI=1 \
    --env HOME=/tmp \
    --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_MAILPIT_URL=http://mailpit:8025/mail \
    --env LEONAID_E2E_ARTIFACT_DIR="/proof/$artifact_path" \
    --env LEONAID_GOLDEN_JOURNEY_ROUND="$round_name" \
    --env-file "$proof/sessions-$round_name.env" \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test \
    --config=tests/e2e/pwa.config.mjs \
    golden-journey.spec.mjs \
    --project=chromium-390 \
    --project=firefox-390 \
    --project=webkit-390 \
    --output="/proof/results-$round_name" \
    --trace=retain-on-failure \
    --reporter=line

  contract verify "$round_name" "/proof/$artifact_path" "/proof/$summary_path" \
    "/proof/$normalized_path"
}

if [ ! -f "$env_file" ]; then
  echo "golden-journey: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

start_golden
run_round round-1 primary primary-round-1.json primary-round-1.normalized.json
run_round round-2 primary primary-round-2.json primary-round-2.normalized.json

start_golden
run_round round-1 repeat repeat-round-1.json repeat-round-1.normalized.json

if ! cmp -s \
  "$proof/primary-round-1.normalized.json" \
  "$proof/repeat-round-1.normalized.json"; then
  echo "golden-journey: ERROR: Wiederholung aus Golden Reset ist nicht deterministisch" >&2
  diff -u \
    "$proof/primary-round-1.normalized.json" \
    "$proof/repeat-round-1.normalized.json" >&2 || true
  exit 1
fi

mkdir -p "$root/.artifacts/poc122"
cp "$proof"/primary-round-*.json "$proof"/repeat-round-1*.json \
  "$root/.artifacts/poc122/"
cp "$proof"/primary/golden-*.png "$proof"/primary/golden-*.pdf \
  "$root/.artifacts/poc122/"

echo "golden-journey: OK: vollständiger Persona-Weg in Chromium, Firefox und WebKit,"
echo "golden-journey:     zwei zusätzliche Fachrunden ohne technische Duplikate"
echo "golden-journey:     sowie deterministische Wiederholung aus Golden Reset bewiesen"
