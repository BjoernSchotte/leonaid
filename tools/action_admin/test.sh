#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_ACTION_ADMIN_TEST_PROJECT:-leonaid-poc052-test}-$suffix
owned=false
http_port=${LEONAID_ACTION_ADMIN_TEST_PORT:-18092}
https_port=${LEONAID_ACTION_ADMIN_TEST_HTTPS_PORT:-18452}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
artifact_directory="$root/.artifacts/poc052"
host_user_id=$(id -u)
host_group_id=$(id -g)

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
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "action-admin-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=160 core-postgres api web proxy >&2 || true
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
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "action-admin-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

# Refuse existing resources and unreadable inventories before Docker mutations.
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$root/tools/surveys/network_override.py" "$isolation_file"
owned=true
compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
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
  api tools/action_admin/contract.py

docker run --rm \
  --network "${project}_edge" \
  --env LEONAID_COMPONENT_API_BASE_URL=http://api:8000 \
  --env LEONAID_COMPONENT_ACTION_ID=20000000-0000-4000-8000-000000000001 \
  --env LEONAID_COMPONENT_SESSION=poc052-10000000-0000-4000-8000-000000000002-real-server-session-token \
  --volume "$root:/workspace" \
  --workdir /workspace \
  "$BUN_IMAGE" \
  bun run --filter @leonaid/web test:components

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env KLARA_SESSION=poc052-10000000-0000-4000-8000-000000000002-real-server-session-token \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/action-admin.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

for screenshot in \
  action-create-guidance.png \
  action-admin-desktop.png \
  action-admin-public.png \
  action-admin-dark.png \
  action-admin-mobile.png \
  action-overview-desktop.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "action-admin-test: ERROR: Browsernachweis $screenshot fehlt" >&2
    exit 1
  fi
done
mkdir -p "$artifact_directory"
cp "$proof/"*.png "$artifact_directory/"

echo "action-admin-test: OK: Server, React-Komponente und Browser-Lebenszyklus gegen echte Dienste bewiesen"
