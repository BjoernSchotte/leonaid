#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project=${LEONAID_POLICY_TEST_PROJECT:-leonaid-poc043-test}
http_port=${LEONAID_POLICY_TEST_PORT:-18089}
https_port=${LEONAID_POLICY_TEST_HTTPS_PORT:-18449}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="$root/tests/fixtures/golden/v1"
proof_dir=$(mktemp -d)
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
    echo "policy-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=100 api core-postgres twenty-server >&2 || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof_dir"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "policy-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api
compose --profile dev-mail up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof_dir:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/twenty/provision.py apply \
  --token-output /proof/integration.env

integration_key=$(sed -n 's/^TWENTY_INTEGRATION_API_KEY=//p' \
  "$proof_dir/integration.env")
if [ "${#integration_key}" -lt 32 ]; then
  echo "policy-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof_dir/pdfs" "${project}-api"

compose --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof_dir/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose run --rm --no-deps \
  --env-from-file "$proof_dir/integration.env" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof_dir:/proof:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/twenty/provision.py verify-key \
  --token-file /proof/integration.env

compose run --rm --no-deps \
  --env-from-file "$proof_dir/integration.env" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/policy/contract.py \
  /repo/tests/fixtures/golden/v1/dataset.json

echo "policy-test: OK: zentrale Row-Level-Policies gegen PostgreSQL und Twenty bewiesen"
