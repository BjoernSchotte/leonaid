#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_PUBLIC_ORDER_TEST_PROJECT:-leonaid-poc072-test}-$suffix
owned=false
http_port=${LEONAID_PUBLIC_ORDER_TEST_PORT:-18097}
https_port=${LEONAID_PUBLIC_ORDER_TEST_HTTPS_PORT:-18457}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
integration_key=""

compose() {
  LEONAID_HTTP_PORT="$http_port" \
    LEONAID_HTTPS_PORT="$https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
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
    echo "public-order-test: diagnostics for the failed real services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=180 \
      api core-postgres twenty-server twenty-worker public proxy >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  if [ "$owned" = true ]; then
    if ! compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
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

if [ ! -f "$env_file" ]; then
  echo "public-order-test: ERROR: .env.local is missing; run ./leonaid bootstrap first" >&2
  exit 1
fi

if [ -n "${LEONAID_TEST_STACK:-}" ]; then
  shared_services="api twenty-worker mailpit"
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
compose build api public pwa web
compose up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/twenty/provision.py apply \
  --token-output /proof/integration.env

integration_key=$(sed -n 's/^TWENTY_INTEGRATION_API_KEY=//p' \
  "$proof/integration.env")
if [ "${#integration_key}" -lt 32 ]; then
  echo "public-order-test: ERROR: restricted Twenty key is missing" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${project}-api"

fi

compose --profile dev-mail run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --env-from-file "$proof/integration.env" \
  --env API_BASE_URL=http://api:8000 \
  --env TWENTY_BASE_URL=http://twenty-server:3000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/public_orders/contract.py

compose up --detach --wait --wait-timeout 420 public proxy

# A Charity-Admin session for the delivery-window case of the browser spec.
compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/public_orders/admin_session.py /proof/admin-session.env

# The browser step may switch on delivery windows; undo a leftover from an
# interrupted run first, and always undo it again afterwards. The spec lists
# its windows (and an extended action period) in a state file that outlives
# this run's proof directory, so the next run can undo an interrupted one.
delivery_state="$root/.artifacts/public-orders/delivery-state"
mkdir -p "$delivery_state"
compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$delivery_state:/delivery-state" \
  --workdir /repo \
  --entrypoint python \
  api tools/public_orders/delivery_cleanup.py /delivery-state/state.json
set +e
docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env LEONAID_E2E_DELIVERY_STATE=/delivery-state/state.json \
  --env-file "$proof/admin-session.env" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --volume "$delivery_state:/delivery-state" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/public.config.mjs \
  public-orders.spec.mjs \
  ${LEONAID_E2E_SMOKE:+--grep "new company, existing company and private person order in the guided form"} \
  --project=chromium \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line
browser_status=$?
set -e
compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$delivery_state:/delivery-state" \
  --workdir /repo \
  --entrypoint python \
  api tools/public_orders/delivery_cleanup.py /delivery-state/state.json
[ "$browser_status" -eq 0 ]

compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --env-from-file "$proof/integration.env" \
  --env TWENTY_BASE_URL=http://twenty-server:3000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --env UI_PROOF_PATH=/proof/public-orders-ui-proof.json \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/public_orders/verify_ui.py

for artifact in \
  public-order-form-mobile.png \
  public-order-validation-mobile.png \
  public-order-success-new-company.png \
  public-order-success-existing-company.png \
  public-order-success-person.png \
  public-order-form-desktop.png \
  public-orders-ui-proof.json; do
  if [ ! -s "$proof/$artifact" ]; then
    echo "public-order-test: ERROR: browser evidence is missing: $artifact" >&2
    exit 1
  fi
done

mkdir -p "$root/.artifacts/poc072"
cp "$proof"/public-order-*.png "$root/.artifacts/poc072/"
cp "$proof/public-orders-ui-proof.json" "$root/.artifacts/poc072/"

echo "public-order-test: OK: real Core/Twenty contract, visible form UX,"
echo "public-order-test:     three order paths, idempotency, protection rules and ActivityEvents proven"
