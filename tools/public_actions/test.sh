#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_PUBLIC_ACTIONS_TEST_PROJECT:-leonaid-poc070-test}-$suffix
owned=false
http_port=${LEONAID_PUBLIC_ACTIONS_TEST_PORT:-18093}
https_port=${LEONAID_PUBLIC_ACTIONS_TEST_HTTPS_PORT:-18453}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
artifact_directory="$root/.artifacts/poc071"
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
  if [ "$status" -ne 0 ] && { [ "$owned" = true ] || [ -n "${LEONAID_TEST_STACK:-}" ]; }; then
    echo "public-actions-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=180 core-postgres api public proxy >&2 || true
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

if [ ! -f "$env_file" ]; then
  echo "public-actions-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services="proxy"
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
compose up --build --detach --wait --wait-timeout 420 proxy

fi

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
  --env PUBLIC_BASE_URL=http://public:3000 \
  --env PYTHONPATH=/repo/src:/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/public_actions/contract.py

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
  --config=tests/e2e/public.config.mjs \
  public-actions.spec.mjs \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

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
  tests/e2e/public-audit.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results-audit \
  --trace=retain-on-failure \
  --reporter=line

for screenshot in \
  public-active-chromium-390.png \
  public-active-firefox-390.png \
  public-active-webkit-390.png \
  public-active-chromium-1440.png \
  public-archive-chromium-1440.png \
  public-inactive-chromium-390.png; do
  if [ ! -s "$proof/$screenshot" ]; then
    echo "public-actions-test: ERROR: Browsernachweis $screenshot fehlt" >&2
    exit 1
  fi
done
for report in accessibility-report.json performance-report.json; do
  if [ ! -s "$proof/$report" ]; then
    echo "public-actions-test: ERROR: Qualitätsbericht $report fehlt" >&2
    exit 1
  fi
done
mkdir -p "$artifact_directory"
cp "$proof/"*.png "$proof/"*.json "$artifact_directory/"

echo "public-actions-test: OK: Astro/Core-Parität, drei Browser, responsive Public UX,"
echo "public-actions-test:     Alias/Archiv, WCAG 2.2 AA und Web-Vitals real bewiesen"
