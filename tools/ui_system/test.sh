#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_UI_SYSTEM_TEST_PROJECT:-leonaid-poc100-test}
http_port=${LEONAID_UI_SYSTEM_TEST_PORT:-18120}
https_port=${LEONAID_UI_SYSTEM_TEST_HTTPS_PORT:-18480}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
artifact_directory="$root/.artifacts/poc100"
snapshot_mode=${LEONAID_UPDATE_SCREENSHOTS:-0}

compose() {
  LEONAID_HTTP_PORT="$http_port" \
    LEONAID_HTTPS_PORT="$https_port" \
    docker compose \
      --project-name "$project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "ui-system-test: Diagnose der fehlgeschlagenen Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=220 \
      api core-postgres web proxy twenty-server >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "ui-system-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose up --build --detach --wait --wait-timeout 420 proxy

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
  --volume "$workspace_mount" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/pwa.config.mjs \
  ui-system.spec.mjs \
  --project=chromium-1440 \
  --output=/tmp/leonaid-ui-system-results \
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
