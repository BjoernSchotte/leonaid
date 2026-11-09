# Sourced by module browser leaves (tools/<module>/test.sh) inside a borrowed
# shared stack. Expects root, leaf and module_specs; seeds two synthetic
# accounts and runs the module's Playwright specs against the real proxy.
# Optional: shared_services (services the leaf needs), module_seed (a
# repository script that extends the fixture with module data) and
# module_smoke_grep (the test the CI smoke leg runs when LEONAID_E2E_SMOKE=1).
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
integration_key=""
shared_leaf_owned=false

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "$leaf: diagnostics for the failed real services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=160 api web pwa proxy rustfs >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" "$root" "$proof" "$project" || true
  fi
  if [ "$shared_leaf_owned" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

shared_services=${shared_services:-"api web pwa proxy rustfs"}
# Task, knowledge and inbox modules never reach the CRM.
shared_crm=none
. "$root/tools/testing/borrow_stack.sh"

compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  --env LEONAID_MODULE_FIXTURE=/proof/module-fixture.json \
  --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --entrypoint python api /repo/tools/testing/module_browser_seed.py
if [ -n "${module_seed:-}" ]; then
  compose run --rm --no-deps --user "$(id -u):$(id -g)" \
    --env LEONAID_MODULE_FIXTURE=/proof/module-fixture.json \
    --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --entrypoint python api "/repo/$module_seed"
fi

smoke_grep=""
if [ -n "${LEONAID_E2E_SMOKE:-}" ]; then
  if [ -z "${module_smoke_grep:-}" ]; then
    echo "$leaf: ERROR: no smoke test defined (module_smoke_grep)" >&2
    exit 64
  fi
  smoke_grep=$module_smoke_grep
fi
# Intentional splitting of the module's spec list.
# shellcheck disable=SC2086
docker run --rm --network "${project}_edge" \
  --user "$(id -u):$(id -g)" \
  --env CI=1 --env HOME=/tmp --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_MODULE_FIXTURE=/proof/module-fixture.json \
  --volume "$root:/workspace:ro" --volume "$proof:/proof" --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" node_modules/.bin/playwright test $module_specs \
  ${smoke_grep:+--grep "$smoke_grep"} \
  --output=/proof/test-results --trace=retain-on-failure --reporter=line
