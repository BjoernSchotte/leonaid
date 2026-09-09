#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_UI_SYSTEM_TEST_PROJECT:-leonaid-poc100-test}-$suffix
owned=false
http_port=${LEONAID_UI_SYSTEM_TEST_PORT:-18120}
https_port=${LEONAID_UI_SYSTEM_TEST_HTTPS_PORT:-18480}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
artifact_directory="$root/.artifacts/poc100"
browser_results="$root/.artifacts/ui-system-browser/$project"
snapshot_mode=${LEONAID_UPDATE_SCREENSHOTS:-0}

compose() {
  LEONAID_HTTP_PORT="$http_port" \
    LEONAID_HTTPS_PORT="$https_port" \
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
    echo "ui-system-test: Diagnose der fehlgeschlagenen Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=220 \
      api core-postgres web proxy twenty-server >&2 || true
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

if [ ! -f "$env_file" ]; then
  echo "ui-system-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

mkdir -p "$browser_results"
chmod 700 "$browser_results"
if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services="proxy"
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
compose up --build --detach --wait --wait-timeout 420 proxy
fi

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo/src:/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/seed/golden.py seed-core /repo/tests/fixtures/golden/v1

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

session_mode=$(stat -c '%a' "$proof/sessions.env" 2>/dev/null || \
  stat -f '%Lp' "$proof/sessions.env")
if [ "$session_mode" != "600" ]; then
  echo "ui-system-test: ERROR: Browser-Sitzung ist nicht Modus 600" >&2
  exit 1
fi

snapshot_argument=
workspace_mount="$root:/workspace:ro"
if [ "$snapshot_mode" = "1" ]; then
  snapshot_argument=--update-snapshots=all
  workspace_mount="$root:/workspace"
fi

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env-file "$proof/sessions.env" \
  --volume "$browser_results:/browser-results" \
  --volume "$workspace_mount" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/pwa.config.mjs \
  ui-system.spec.mjs \
  --project=chromium-1440 \
  --output=/browser-results/run \
  --trace=retain-on-failure \
  --reporter=line \
  $snapshot_argument

for screenshot in \
  ui-system-desktop.png \
  ui-system-desktop-collapsed.png \
  ui-system-dark.png \
  ui-system-mobile.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "ui-system-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done

mkdir -p "$artifact_directory"
cp "$proof"/ui-system-*.png "$artifact_directory/"

echo "ui-system-test: OK: reale Golden-Identität, UI-Patterns, Light/Dark,"
echo "ui-system-test:     A11y und visuelle Shell-Regressionen bewiesen"
