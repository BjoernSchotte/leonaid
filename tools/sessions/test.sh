#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_SESSION_TEST_PROJECT:-leonaid-poc042-test}
port=18088
https_port=18448
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
fixture="/repo/tests/fixtures/golden/v1"
proof=$(mktemp -d)
artifact_directory="$root/.artifacts/poc042"
host_user_id=$(id -u)
host_group_id=$(id -g)

if [ ! -f "$env_file" ]; then
  echo "session-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

export LEONAID_HTTP_PORT="$port"
export LEONAID_HTTPS_PORT="$https_port"
export LEONAID_FRESH_LOGIN_SECONDS=5

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --profile dev-mail \
    "$@"
}

diagnose() {
  compose ps >&2 || true
  compose logs --no-color --tail=180 \
    core-postgres api worker mailpit web pwa public proxy >&2 || true
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "session-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    diagnose
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

run_python() {
  compose run --rm --no-deps \
    --user "$host_user_id:$host_group_id" \
    --env-from-file "$env_file" \
    --env LEONAID_API_BASE_URL=http://api:8000 \
    --env PYTHONPATH=/repo/src:/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --workdir /repo \
    --entrypoint python \
    api "$@"
}

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose up --build --detach --wait --wait-timeout 420 \
  proxy worker mailpit

run_python tools/seed/golden.py seed-core "$fixture"
run_python tools/sessions/contract.py

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_MAILPIT_URL=http://mailpit:8025/mail \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/sessions.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

mkdir -p "$artifact_directory"
for screenshot in \
  session-fresh-admin.png \
  session-login.png \
  session-finance-default-route.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "session-test: ERROR: Browser-Screenshot fehlt: $screenshot" >&2
    exit 1
  fi
  cp "$proof/$screenshot" "$artifact_directory/"
done

echo "session-test: OK: Login, 90 Tage, Fresh Login und Widerruf real bewiesen"
