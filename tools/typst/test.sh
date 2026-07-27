#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_TYPST_TEST_PROJECT:-leonaid-poc091-test}
http_port=${LEONAID_TYPST_TEST_PORT:-18111}
https_port=${LEONAID_TYPST_TEST_HTTPS_PORT:-18471}
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
    echo "typst-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=180 \
      api core-postgres twenty-server twenty-worker rustfs >&2 || true
  fi
  compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "typst-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api
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
  echo "typst-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/seed-pdfs" "${project}-api"

compose --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/seed-pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/typst/export_snapshots.py \
  tests/fixtures/golden/v1/documents \
  /proof/database-snapshots.json

docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=192m \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  --env PYTHONPATH=/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --entrypoint python \
  "${project}-api" \
  /repo/tools/typst/render_contract.py \
  /proof/database-snapshots.json \
  /repo/tests/fixtures/golden/v1/documents \
  /proof/rendered

verify_pdfs() {
  docker run --rm \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=256m \
    --user "$(id -u):$(id -g)" \
    --env HOME=/tmp \
    --env PYTHONPATH=/workspace/src \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    "$UV_IMAGE" \
    uv run --frozen --no-sync python tools/typst/verify_pdfs.py \
    /proof/rendered \
    /proof/pages \
    --template src/leonaid/adapters/typst/templates/invoice-v1.typ \
    "$@"
}

if [ "${LEONAID_TYPST_APPROVAL_CANDIDATE:-0}" = "1" ]; then
  echo "typst-test: HINWEIS: Erzeuge nur visuelle Freigabekandidaten."
  verify_pdfs
else
  verify_pdfs --golden-directory tests/fixtures/typst/v1/golden
fi

mkdir -p "$root/.artifacts/poc091"
cp "$proof/database-snapshots.json" "$root/.artifacts/poc091/"
cp "$proof/rendered/contract-manifest.json" "$root/.artifacts/poc091/"
cp "$proof/rendered/"*.pdf "$root/.artifacts/poc091/"
cp "$proof/pages/"*.png "$root/.artifacts/poc091/"

echo "typst-test: OK: echter Typst $(
  docker run --rm --entrypoint typst "${project}-api" --version
)"
echo "typst-test:     Datenbank-Snapshots, Determinismus, Golden-Layout,"
echo "typst-test:     Metadaten, eingebettete Fonts und zwei PDF-Engines bewiesen"
