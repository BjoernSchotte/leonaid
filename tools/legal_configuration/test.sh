#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"

project=${LEONAID_LEGAL_TEST_PROJECT:-leonaid-pilot044-test}
http_port=${LEONAID_LEGAL_TEST_PORT:-18124}
https_port=${LEONAID_LEGAL_TEST_HTTPS_PORT:-18484}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
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
    echo "legal-configuration-test: diagnostics:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=260 \
      api core-postgres web proxy twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1 || true
  verify_owned_project_removed "$project" || status=1
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "legal-configuration-test: ERROR: .env.local is missing" >&2
  exit 1
fi

docker run --rm \
  --env HOME=/tmp \
  --env UV_CACHE_DIR=/tmp/uv-cache \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$UV_IMAGE" \
  uv run --frozen --no-sync \
  pytest -p no:cacheprovider tests/unit/test_legal_configuration.py --quiet

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
build_shared_images api
if ! compose --profile dev-mail up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker; then
  echo "legal-configuration-test: retrying Twenty start once"
  compose --profile dev-mail up --detach --wait --wait-timeout 420 \
    core-postgres rustfs mailpit twenty-server twenty-worker
fi

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
  echo "legal-configuration-test: ERROR: Twenty key is missing" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${project}-api"

compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

for step in prepare act assert; do
  compose run --rm --no-deps \
    --user "$(id -u):$(id -g)" \
    --env-from-file "$env_file" \
    --env API_BASE_URL=http://api:8000 \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --workdir /repo \
    --entrypoint python \
    api tools/legal_configuration/contract.py "$step"
done

echo "legal-configuration-test: OK: real PostgreSQL versioning and"
echo "legal-configuration-test:     four-eyes activation proven"
