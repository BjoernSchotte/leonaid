#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc110-test-$suffix
owned=false
http_port=18130
https_port=18490
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
artifact_directory="$root/.artifacts/poc110"

if [ ! -f "$env_file" ]; then
  echo "security-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

export LEONAID_HTTP_PORT="$http_port"
export LEONAID_HTTPS_PORT="$https_port"
export TWENTY_INTEGRATION_API_KEY=""

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    --profile dev-mail \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && { [ "$owned" = true ] || [ -n "${LEONAID_TEST_STACK:-}" ]; }; then
    echo "security-test: Diagnose der echten Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=220 \
      api core-postgres proxy pwa web public twenty-server rustfs >&2 || true
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
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

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
compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
compose up --build --detach --wait --wait-timeout 420 proxy
fi

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/seed/golden.py seed-core /repo/tests/fixtures/golden/v1

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env CORE_DATABASE_URL=postgresql://leonaid:"$(sed -n 's/^CORE_POSTGRES_PASSWORD=//p' "$env_file")"@core-postgres:5432/leonaid \
  --env LEONAID_SECURITY_CANARY_FILE=/proof/canary \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/security/contract.py

canary=$(sed -n '1p' "$proof/canary")
if [ -z "$canary" ]; then
  echo "security-test: ERROR: Secret-Canary fehlt" >&2
  exit 1
fi
if compose logs --no-color api proxy | grep -F "$canary" >/dev/null; then
  echo "security-test: ERROR: Secret-Canary steht in Service-Logs" >&2
  exit 1
fi

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/security.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

if [ ! -s "$proof/security-rate-limit.png" ]; then
  echo "security-test: ERROR: Browser-Nachweis fehlt" >&2
  exit 1
fi
mkdir -p "$artifact_directory"
cp "$proof/security-rate-limit.png" "$artifact_directory/"

echo "security-test: OK: Transportgrenze, Missbrauchsschutz und Browser-UX bewiesen"
