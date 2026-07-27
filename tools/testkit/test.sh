#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_TESTKIT_PROJECT:-leonaid-poc013-test}
http_port=${LEONAID_TESTKIT_PORT:-18113}
https_port=${LEONAID_TESTKIT_HTTPS_PORT:-18473}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
proof=$(mktemp -d)
integration_key=""
e2e_spec=${LEONAID_TESTKIT_E2E_SPEC:-testkit.spec.mjs}

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
    echo "testkit-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=180 \
      api worker core-postgres rustfs mailpit \
      twenty-server twenty-worker pwa proxy >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "testkit-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api pwa public web
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
  echo "testkit-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${project}-api"

compose --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose up --detach --wait --wait-timeout 420 worker

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env-from-file "$proof/integration.env" \
  --env LEONAID_API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo/packages/testkit:/repo/src:/repo:/workspace/src \
  --env TESTKIT_PROOF_DIR=/proof \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/testkit/smoke.py

set -a
. "$proof/persona-session.env"
set +a

compose up --detach --wait --wait-timeout 420 public pwa web proxy

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env ANNA_SESSION="$ANNA_SESSION" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/pwa.config.mjs \
  "$e2e_spec" \
  --project=chromium-1440 \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

compose run --rm --no-deps \
  --env PYTHONPATH=/repo/packages/testkit \
  --env TESTKIT_PROOF_DIR=/proof \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/testkit/verify_ui.py

for artifact in api-proof.json ui-proof.json testkit-ui.png; do
  if [ ! -s "$proof/$artifact" ]; then
    echo "testkit-test: ERROR: Nachweis fehlt: $artifact" >&2
    exit 1
  fi
done

mkdir -p "$root/.artifacts/poc013"
cp "$proof/api-proof.json" "$root/.artifacts/poc013/"
cp "$proof/ui-proof.json" "$root/.artifacts/poc013/"
cp "$proof/testkit-ui.png" "$root/.artifacts/poc013/"

echo "testkit-test: OK: gemeinsame Echt-System-Clients, Magic-Link-Persona,"
echo "testkit-test:     UI/API/Twenty/SQL-ID, SMTP/Mailpit und RustFS-Hash bewiesen"
