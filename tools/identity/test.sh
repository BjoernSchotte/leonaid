#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_IDENTITY_TEST_PROJECT:-leonaid-poc040-test}-$suffix
owned=false
port=18086
https_port=18446
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
fixture="/repo/tests/fixtures/golden/v1"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
artifact_directory="$root/.local/pilot/evidence/identity"
host_user_id=$(id -u)
host_group_id=$(id -g)

if [ ! -f "$env_file" ]; then
  echo "identity-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap ausführen" >&2
  exit 1
fi

export LEONAID_HTTP_PORT="$port"
export LEONAID_HTTPS_PORT="$https_port"

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    --profile dev-mail \
    "$@"
}

diagnose() {
  compose ps >&2 || true
  compose logs --no-color --tail=120 \
    core-postgres api worker web pwa proxy mailpit >&2 || true
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && { [ "$owned" = true ] || [ -n "${LEONAID_TEST_STACK:-}" ]; }; then
    echo "identity-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    diagnose
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  if [ "$owned" = true ]; then
    if ! compose down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
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
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
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

if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services="proxy worker mailpit"
  . "$root/tools/testing/borrow_stack.sh"
else
# Refuse existing resources; never clear a project selected by another worktree.
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$root/tools/surveys/network_override.py" "$isolation_file"
owned=true
compose up --build --detach --wait --wait-timeout 420 proxy worker mailpit

fi

run_python tools/seed/golden.py seed-core "$fixture"
run_python tools/identity/contract.py \
  --session-output /proof/sessions.env

if stat -c '%a' "$proof/sessions.env" >/dev/null 2>&1; then
  session_mode=$(stat -c '%a' "$proof/sessions.env")
else
  session_mode=$(stat -f '%Lp' "$proof/sessions.env")
fi
if [ "$session_mode" != "600" ]; then
  echo "identity-test: ERROR: Sitzungsdatei besitzt nicht Dateimodus 0600" >&2
  exit 1
fi

docker run --rm \
  --network "${project}_edge" \
  --env-file "$proof/sessions.env" \
  --env HOME=/tmp \
  --env CI=1 \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_MAILPIT_URL=https://proxy:8443/mail \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/identity.spec.mjs \
  tests/e2e/y-role-management.spec.mjs \
  tests/e2e/z-account-status.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

for screenshot in \
  charity-admin-desktop.png \
  acquirer-mobile.png \
  acquirer-admin-redirect.png \
  system-members-desktop.png \
  charity-members-mobile.png \
  role-charity-scope.png \
  roles-assigned.png \
  roles-offboarded.png \
  account-status-suspended.png \
  account-status-reactivated.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "identity-test: ERROR: Browsernachweis fehlt: $screenshot" >&2
    exit 1
  fi
done
mkdir -p "$artifact_directory"
chmod 700 "$root/.local/pilot" "$root/.local/pilot/evidence" "$artifact_directory"
for screenshot in \
  charity-admin-desktop.png \
  acquirer-mobile.png \
  acquirer-admin-redirect.png \
  system-members-desktop.png \
  charity-members-mobile.png \
  role-charity-scope.png \
  roles-assigned.png \
  roles-offboarded.png \
  account-status-suspended.png \
  account-status-reactivated.png; do
  cp "$proof/$screenshot" "$artifact_directory/"
  chmod 600 "$artifact_directory/$screenshot"
done

echo "identity-test: OK: Mitgliederübersicht, Rollen-Offboarding, Statusworkflow, Konkurrenz, Sitzungsentzug und Persona-Navigation real bewiesen"
