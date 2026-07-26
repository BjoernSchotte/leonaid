#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_PUBLIC_ORDER_TEST_PROJECT:-leonaid-poc072-test}
http_port=${LEONAID_PUBLIC_ORDER_TEST_PORT:-18097}
https_port=${LEONAID_PUBLIC_ORDER_TEST_HTTPS_PORT:-18457}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
proof=$(mktemp -d)
integration_key=""

compose() {
  LEONAID_HTTP_PORT="$http_port" \
    LEONAID_HTTPS_PORT="$https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "public-order-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=180 \
      api core-postgres twenty-server twenty-worker public proxy >&2 || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "public-order-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api public pwa web
compose up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker

compose run --rm --no-deps \
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
  echo "public-order-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

mkdir -p "$proof/pdfs"
for source in "$fixture"/documents/KT26-*.typ; do
  filename=$(basename "$source" .typ)
  docker run --rm \
    --volume "$fixture/documents:/input:ro" \
    --volume "$proof/pdfs:/output" \
    "$TYPST_IMAGE" \
    compile \
    --creation-timestamp 1782864000 \
    --jobs 1 \
    "/input/$filename.typ" \
    "/output/$filename.pdf"
done

compose --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose run --rm --no-deps \
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

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/public.config.mjs \
  public-orders.spec.mjs \
  --project=chromium \
  --output=/proof/test-results \
  --reporter=line

compose run --rm --no-deps \
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
    echo "public-order-test: ERROR: Browsernachweis fehlt: $artifact" >&2
    exit 1
  fi
done

mkdir -p "$root/.artifacts/poc072"
cp "$proof"/public-order-*.png "$root/.artifacts/poc072/"
cp "$proof/public-orders-ui-proof.json" "$root/.artifacts/poc072/"

echo "public-order-test: OK: realer Core/Twenty-Vertrag, sichtbare Formular-UX,"
echo "public-order-test:     drei Bestellwege, Idempotenz, Schutzregeln und ActivityEvents bewiesen"
