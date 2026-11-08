#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(CDPATH= cd -- "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc023-test-$suffix
owned=false
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    "$@"
}

cleanup() {
  status=$?
  if [ "$owned" = true ]; then
    if ! compose --profile '*' down --volumes --remove-orphans --timeout 5 >/dev/null 2>&1; then status=1; fi
    if ! verify_owned_project_removed "$project"; then status=1; fi
    if [ "$status" -eq 0 ]; then echo "test-isolation: $project passed and owned resources were removed"; fi
  fi
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

# Generation, frontend boundary, client types and formatting are static
# checks of the Lint job (tools/ci/lint-types.sh) and ./leonaid check; this
# suite proves only the generated client against a real API.

# The live contract needs only a running API; a leaf of the shared feature
# fixture (./leonaid test-integration) borrows its restored stack instead of
# a cold Twenty installation. Standalone runs (CI api-contract) own a stack.
if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services=api
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
  # Twenty boots (about 75 s) while the API images build.
  compose up --detach --wait --wait-timeout 420 twenty-server &
  twenty_pid=$!
  build_status=0
  build_shared_images api survey-validator || build_status=$?
  twenty_status=0
  wait "$twenty_pid" || twenty_status=$?
  if [ "$build_status" -ne 0 ] || [ "$twenty_status" -ne 0 ]; then
    echo "poc023-test: ERROR: API build ($build_status) or Twenty start ($twenty_status) failed" >&2
    exit 1
  fi
  compose up --detach --wait --wait-timeout 420 api
fi

docker run --rm \
  --network "${project}_edge" \
  -v "$root:/workspace:ro" \
  -w /workspace \
  "$BUN_IMAGE" \
  bun tests/contract/api_client.ts

echo "poc023-test: OK: generated client proven against the real API"
