#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project=${LEONAID_PUBLIC_ACTIONS_TEST_PROJECT:-leonaid-poc070-test}
http_port=${LEONAID_PUBLIC_ACTIONS_TEST_PORT:-18093}
https_port=${LEONAID_PUBLIC_ACTIONS_TEST_HTTPS_PORT:-18453}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
artifact_directory="$root/.artifacts/poc070"
host_user_id=$(id -u)
host_group_id=$(id -g)

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
    echo "public-actions-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=180 core-postgres api public proxy >&2 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "public-actions-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose up --build --detach --wait --wait-timeout 420 proxy

compose run --rm --no-deps \
  --user "$host_user_id:$host_group_id" \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo/src:/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/seed/golden.py seed-core \
  /repo/tests/fixtures/golden/v1

compose run --rm --no-deps \
  --user "$host_user_id:$host_group_id" \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo/src:/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/public_actions/contract.py

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/public-actions.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results \
  --reporter=line

for screenshot in \
  public-alias-2027.png \
  public-archive-2026.png \
  public-inactive.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "public-actions-test: ERROR: Browsernachweis $screenshot fehlt" >&2
    exit 1
  fi
done
mkdir -p "$artifact_directory"
cp "$proof/"*.png "$artifact_directory/"

echo "public-actions-test: OK: Aliaswechsel, Archiv und neutrale Public UX real bewiesen"
