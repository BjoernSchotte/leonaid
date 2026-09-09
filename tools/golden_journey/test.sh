#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_GOLDEN_JOURNEY_PROJECT:-leonaid-poc122-test}-$suffix
owned=false
http_port=${LEONAID_GOLDEN_JOURNEY_PORT:-18142}
https_port=${LEONAID_GOLDEN_JOURNEY_HTTPS_PORT:-18502}
compose_file="$root/infra/compose/compose.yml"
network_overlay="$root/infra/upgrade/compose.rollback-network.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
browser_results="$root/.artifacts/golden-journey-browser/$project"
isolation_file="$proof/compose-isolation.yml"
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
      --file "$isolation_file" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && { [ "$owned" = true ] || [ -n "${LEONAID_TEST_STACK:-}" ]; }; then
    echo "golden-journey: Diagnose der fehlgeschlagenen Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=400 \
      api worker public pwa web proxy core-postgres rustfs mailpit \
      twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  if [ "$owned" = true ]; then
    if ! compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    for inventory in containers volumes networks; do
      case "$inventory" in
        containers) remaining=$(docker ps -aq --filter "label=com.docker.compose.project=$project") || status=1 ;;
        volumes) remaining=$(docker volume ls -q --filter "label=com.docker.compose.project=$project") || status=1 ;;
        networks) remaining=$(docker network ls -q --filter "label=com.docker.compose.project=$project") || status=1 ;;
      esac
      if [ -n "$remaining" ]; then
        echo "test-isolation: owned $inventory remain for $project" >&2
        status=1
      fi
    done
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

contract() {
  compose run --rm --no-deps \
    --user "$(id -u):$(id -g)" \
    --env-from-file "$env_file" \
    --env API_BASE_URL=http://api:8000 \
    --env MAIL_TEST_API_URL=http://mailpit:8025/mail \
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
  journey_generation=$((journey_generation + 1))
  if [ -n "${LEONAID_TEST_STACK:-}" ]; then
    test "$journey_generation" -eq 1
    # The parallel repeat job still proves a completely fresh installation.
    # This job proves the same journey from a private initialized template.
    compose run --rm --no-deps \
      --env-from-file "$env_file" \
      --volume "$root:/repo:ro" --volume "$proof/pdfs:/proof/pdfs:ro" \
      --entrypoint python api /repo/tools/seed/golden.py seed \
      /repo/tests/fixtures/golden/v1 /proof/pdfs
    compose --profile dev-mail up --detach --wait --wait-timeout 420 \
      worker public pwa web proxy
    return
  fi
  integration_key=""
  token_filename="integration-$journey_generation.env"
  if [ "$journey_generation" -gt 1 ]; then
    # Reset only the stack acquired by this invocation, before reseeding it.
    compose --profile '*' down --volumes --remove-orphans
    python3 "$root/tools/surveys/network_override.py" "$isolation_file"
  fi
  compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
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
  session_mode=$(stat -c '%a' "$proof/sessions-$round_name.env" 2>/dev/null || \
    stat -f '%Lp' "$proof/sessions-$round_name.env")
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
    --volume "$browser_results:/browser-results" \
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
    --output="/browser-results/generation-$journey_generation-$round_name" \
    --trace=retain-on-failure \
    --reporter=line

  contract verify "$round_name" "/proof/$artifact_path" "/proof/$summary_path" \
    "/proof/$normalized_path"
}

if [ ! -f "$env_file" ]; then
  echo "golden-journey: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

# Refuse existing resources and unreadable inventories before Docker mutations.
if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  test "${LEONAID_GOLDEN_PART:-}" = primary
  shared_services="api twenty-worker mailpit"
  . "$root/tools/testing/borrow_stack.sh"
else
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$root/tools/surveys/network_override.py" "$isolation_file"
owned=true
fi
mkdir -p "$browser_results"
chmod 700 "$browser_results"

start_golden
run_round round-1 primary primary-round-1.json primary-round-1.normalized.json
if [ -n "${LEONAID_GOLDEN_PART:-}" ]; then
  case "$LEONAID_GOLDEN_PART" in
    primary) run_round round-2 primary primary-round-2.json primary-round-2.normalized.json ;;
    repeat) ;;
    *) echo 'Unknown Golden Journey part' >&2; exit 64 ;;
  esac
  # Only a digest crosses jobs, never session files or business evidence.
  test -n "${LEONAID_CI_ARTIFACT_DIR:-}"
  mkdir -p "$LEONAID_CI_ARTIFACT_DIR"
  sha256sum "$proof/primary-round-1.normalized.json" | cut -d ' ' -f 1 > "$LEONAID_CI_ARTIFACT_DIR/comparison.sha256"
  echo "golden-journey: $LEONAID_GOLDEN_PART passed; fresh/template results compared by the parent workflow"
  exit 0
fi
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

private_evidence="$root/.local/pilot/evidence/golden-journey"
mkdir -p "$private_evidence"
chmod 700 "$root/.local" "$root/.local/pilot" \
  "$root/.local/pilot/evidence" "$private_evidence"
cp "$proof"/primary-round-*.json "$proof"/repeat-round-1*.json \
  "$private_evidence/"
cp "$proof"/primary/golden-*.png "$proof"/primary/golden-*.pdf \
  "$private_evidence/"
find "$private_evidence" -type f -exec chmod 600 {} +

echo "golden-journey: OK: vollständiger Persona-Weg in Chromium, Firefox und WebKit,"
echo "golden-journey:     zwei zusätzliche Fachrunden ohne technische Duplikate"
echo "golden-journey:     sowie deterministische Wiederholung aus Golden Reset bewiesen"
