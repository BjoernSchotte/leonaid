#!/bin/sh
# Browser proof for the tasks module in the web shell and the 390 px PWA.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  # A borrowed shared stack owns every Docker resource of this run.
  exec python3 "$root/tools/testing/shared_stack.py" core tools/tasks/test.sh
fi
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
integration_key=""
shared_leaf_owned=false

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "tasks-test: diagnostics for the failed real services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=160 api web pwa proxy >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" "$root" "$proof" "$project" || true
  fi
  if [ "$shared_leaf_owned" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

shared_services="api web pwa proxy"
. "$root/tools/testing/borrow_stack.sh"

compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  --env LEONAID_MODULE_FIXTURE=/proof/module-fixture.json \
  --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --entrypoint python api /repo/tools/testing/module_browser_seed.py

docker run --rm --network "${project}_edge" \
  --user "$(id -u):$(id -g)" \
  --env CI=1 --env HOME=/tmp --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_MODULE_FIXTURE=/proof/module-fixture.json \
  --volume "$root:/workspace:ro" --volume "$proof:/proof" --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" node_modules/.bin/playwright test \
  tests/e2e/modules-tasks.spec.mjs tests/e2e/tasks-details.spec.mjs \
  tests/e2e/tasks-views.spec.mjs tests/e2e/tasks-planning.spec.mjs \
  tests/e2e/tasks-ordering.spec.mjs tests/e2e/tasks-structure.spec.mjs \
  --output=/proof/test-results --trace=retain-on-failure --reporter=line

echo "tasks-test: OK: web and PWA task journeys, planning, ordering and details"
