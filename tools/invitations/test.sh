#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=leonaid-poc041-test
port=18087
https_port=18447
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
fixture="/repo/tests/fixtures/golden/v1"
proof=$(mktemp -d)
artifact_directory="$root/.artifacts/poc041"
host_user_id=$(id -u)
host_group_id=$(id -g)

if [ ! -f "$env_file" ]; then
  echo "invitation-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

export LEONAID_HTTP_PORT="$port"
export LEONAID_HTTPS_PORT="$https_port"

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
  compose logs --no-color --tail=160 \
    core-postgres api worker mailpit web public proxy >&2 || true
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "invitation-test: Diagnose der fehlgeschlagenen echten Services:" >&2
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
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api "$@"
}

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose up --build --detach --wait --wait-timeout 420 \
  proxy worker mailpit

run_python tools/seed/golden.py seed-core "$fixture"
run_python tools/invitations/contract.py \
  --session-output /proof/sessions.env

if stat -c '%a' "$proof/sessions.env" >/dev/null 2>&1; then
  session_mode=$(stat -c '%a' "$proof/sessions.env")
else
  session_mode=$(stat -f '%Lp' "$proof/sessions.env")
fi
if [ "$session_mode" != "600" ]; then
  echo "invitation-test: ERROR: Sitzungsdatei hat nicht Modus 0600" >&2
  exit 1
fi

docker run --rm \
  --network "${project}_edge" \
  --env-file "$proof/sessions.env" \
  --env HOME=/tmp \
  --env CI=1 \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/invitations.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

mkdir -p "$artifact_directory"
for screenshot in invitation-charity-admin.png invitation-code-mobile.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "invitation-test: ERROR: Browser-Screenshot fehlt: $screenshot" >&2
    exit 1
  fi
  cp "$proof/$screenshot" "$artifact_directory/"
done

echo "invitation-test: OK: Berechtigung, Link/Code und echte Mailzustellung bewiesen"
