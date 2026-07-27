#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)

project=${LEONAID_STORAGE_TEST_PROJECT:-leonaid-poc092-test}
http_port=${LEONAID_STORAGE_TEST_PORT:-18112}
https_port=${LEONAID_STORAGE_TEST_HTTPS_PORT:-18472}
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
      --profile dev-mail \
      --profile storage-contract \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "storage-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps --all >&2 || true
    compose logs --no-color --tail=220 \
      api core-postgres rustfs seaweedfs twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "storage-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api worker
compose up --detach --wait --wait-timeout 420 \
  core-postgres rustfs seaweedfs mailpit twenty-server twenty-worker

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
  echo "storage-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
fi

compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${project}-api"

compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs

compose run --rm --no-deps \
  --env PYTHONPATH=/repo:/workspace/src \
  --env RUSTFS_CONTRACT_ENDPOINT_URL=http://rustfs:9000 \
  --env RUSTFS_CONTRACT_BUCKET=leonaid-contract-rustfs \
  --env SEAWEEDFS_CONTRACT_ENDPOINT_URL=http://seaweedfs:8333 \
  --env SEAWEEDFS_CONTRACT_BUCKET=leonaid-contract \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/storage/contract.py \
  tests/fixtures/golden/v1/documents/KT26-0001.json

compose run --rm --no-deps \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/storage/workflow_contract.py prepare /proof/state.json

state_mode=$(stat -c '%a' "$proof/state.json" 2>/dev/null || \
  stat -f '%Lp' "$proof/state.json")
if [ "$state_mode" != "600" ]; then
  echo "storage-test: ERROR: temporäre Sitzungen sind nicht auf Modus 600 begrenzt" >&2
  exit 1
fi

compose stop rustfs
compose run --rm --no-deps \
  --entrypoint python \
  worker -m leonaid.entrypoints.worker.outbox \
  --worker-id poc092-rustfs-stopped \
  --base-backoff-seconds 0 \
  run-once

compose run --rm --no-deps \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/storage/workflow_contract.py assert-failed /proof/state.json

compose up --detach --wait --wait-timeout 180 rustfs
compose run --rm --no-deps \
  --entrypoint python \
  worker -m leonaid.entrypoints.worker.outbox \
  --worker-id poc092-rustfs-recovered \
  --base-backoff-seconds 0 \
  run-until-idle --maximum-events 10

compose run --rm --no-deps \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/storage/workflow_contract.py assert-success \
  /proof/state.json /proof/KT26-0004.pdf

if [ ! -s "$proof/KT26-0004.pdf" ]; then
  echo "storage-test: ERROR: geschützter PDF-Nachweis fehlt" >&2
  exit 1
fi

mkdir -p "$root/.artifacts/poc092"
cp "$proof/KT26-0004.pdf" "$root/.artifacts/poc092/"

echo "storage-test: OK: RustFS und SeaweedFS, privater/versionierter Port,"
echo "storage-test:     realer Ausfall/Retry, Core-RBAC und unveränderliches PDF"
