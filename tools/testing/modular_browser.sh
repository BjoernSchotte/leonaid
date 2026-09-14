#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  exec python3 "$root/tools/testing/shared_stack.py" core tools/testing/modular_browser.sh
fi
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
shared_leaf_owned=false
cleanup() {
  status=$?
  if [ "$shared_leaf_owned" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
shared_services="api web pwa public proxy"
. "$root/tools/testing/borrow_stack.sh"
compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --entrypoint python api /repo/tools/materials/browser_seed.py
# Browser images/traces stay separate from the sanitized public CI log bundle.
results=${LEONAID_MODULE_BROWSER_ARTIFACT_DIR:-$root/.artifacts/modular-browser}
mkdir -p "$results"
results=$(cd "$results" && pwd)
docker run --rm --network "${project}_edge" \
  --user "$(id -u):$(id -g)" \
  --env CI=1 --env HOME=/tmp --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_MODULE_FIXTURE=/proof/material-browser-fixture.json \
  --volume "$root:/workspace:ro" --volume "$proof:/proof" \
  --volume "$results:/results" --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" node_modules/.bin/playwright test \
  tests/e2e/modules-materials.spec.mjs tests/e2e/modules-knowledge.spec.mjs tests/e2e/knowledge-editor.spec.mjs \
  tests/e2e/modules-tasks.spec.mjs tests/e2e/public-inbox-retry.spec.mjs \
  --output=/results/modules --reporter=line
