#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

source_project=${LEONAID_BACKUP_TEST_SOURCE_PROJECT:-leonaid-poc112-source}
target_project=${LEONAID_BACKUP_TEST_TARGET_PROJECT:-leonaid-restore-poc112}
source_http_port=${LEONAID_BACKUP_TEST_SOURCE_PORT:-18122}
source_https_port=${LEONAID_BACKUP_TEST_SOURCE_HTTPS_PORT:-18482}
target_http_port=${LEONAID_BACKUP_TEST_TARGET_PORT:-18123}
target_https_port=${LEONAID_BACKUP_TEST_TARGET_HTTPS_PORT:-18483}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
repository="$proof/repository"
password_file="$proof/restic-password"
artifact_directory="$root/.artifacts/poc112"
integration_key=""
twenty_password=""

source_compose() {
  LEONAID_HTTP_PORT="$source_http_port" \
    LEONAID_HTTPS_PORT="$source_https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$source_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      "$@"
}

target_compose() {
  LEONAID_HTTP_PORT="$target_http_port" \
    LEONAID_HTTPS_PORT="$target_https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$target_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "backup-test: Diagnose der fehlgeschlagenen Services:" >&2
    source_compose ps --all >&2 || true
    target_compose ps --all >&2 || true
    target_compose logs --no-color --tail=240 \
      api core-postgres rustfs twenty-postgres twenty-server proxy >&2 || true
  fi
  source_compose --profile dev-mail down \
    --volumes --remove-orphans >/dev/null 2>&1 || true
  if [ "${LEONAID_BACKUP_KEEP:-false}" != "true" ] || [ "$status" -ne 0 ]; then
    target_compose --profile dev-mail down \
      --volumes --remove-orphans >/dev/null 2>&1 || true
  else
    echo "backup-test: Restore bleibt sichtbar unter http://127.0.0.1:$target_http_port/admin/"
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

[ -f "$env_file" ] || {
  echo "backup-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
}
docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/backup/manifest_test.py
twenty_password=$(sed -n 's/^TWENTY_POSTGRES_PASSWORD=//p' "$env_file" | tail -n 1)
[ -n "$twenty_password" ] || {
  echo "backup-test: ERROR: TWENTY_POSTGRES_PASSWORD fehlt" >&2
  exit 1
}

source_compose --profile dev-mail down \
  --volumes --remove-orphans >/dev/null 2>&1 || true
target_compose --profile dev-mail down \
  --volumes --remove-orphans >/dev/null 2>&1 || true

mkdir -p "$repository"
docker run --rm \
  -v "$proof:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import secrets,pathlib
pathlib.Path("/proof/restic-password").write_text(secrets.token_urlsafe(48)+"\n")'
chmod 600 "$password_file"

source_compose build api public pwa web
source_compose --profile dev-mail up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker
source_compose run --rm --no-deps \
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
[ "${#integration_key}" -ge 32 ] || {
  echo "backup-test: ERROR: eingeschränkter Twenty-Key fehlt" >&2
  exit 1
}
source_compose up --detach --wait --wait-timeout 420 api

/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${source_project}-api"
source_compose --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs
source_compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/dashboard/contract.py

source_compose stop \
  proxy api worker public pwa web twenty-worker twenty-server \
  >/dev/null
source_compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env "TWENTY_DATABASE_URL=postgresql://twenty:${twenty_password}@twenty-postgres:5432/default" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --volume "${source_project}_twenty-server-data:/twenty-storage:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/backup/inventory.py capture \
  --output /proof/before.json \
  --twenty-storage /twenty-storage

recovery_checkpoint=$(date +%s)
LEONAID_COMPOSE_PROJECT="$source_project" \
  LEONAID_HTTP_PORT="$source_http_port" \
  LEONAID_HTTPS_PORT="$source_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_BACKUP_REPOSITORY="$repository" \
  LEONAID_BACKUP_PASSWORD_FILE="$password_file" \
  LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
  /bin/sh "$root/tools/backup/backup.sh" "$root"
backup_finished=$(date +%s)

docker run --rm \
  -v "$proof:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import pathlib
pathlib.Path("/proof/wrong-password").write_text("wrong-password-that-is-long-enough\n")'
chmod 600 "$proof/wrong-password"
if docker run --rm \
  -e RESTIC_REPOSITORY=/repository \
  -e RESTIC_PASSWORD_FILE=/run/secrets/password \
  -v "$repository:/repository:ro" \
  -v "$proof/wrong-password:/run/secrets/password:ro" \
  "$RESTIC_IMAGE" snapshots >/dev/null 2>&1; then
  echo "backup-test: ERROR: falsches Restic-Passwort wurde akzeptiert" >&2
  exit 1
fi
if docker run --rm \
  -v "$repository:/repository:ro" \
  "$ALPINE_IMAGE" \
  grep -R -a -F "Lions Club LeonAid Golden" /repository >/dev/null 2>&1; then
  echo "backup-test: ERROR: Klartext aus Golden Data im Repository gefunden" >&2
  exit 1
fi
if docker run --rm \
  -v "$root:/workspace:ro" \
  -v "$password_file:/run/secrets/password:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/backup/safety.py backup \
  --project leonaid \
  --repository "$repository" \
  --password-file /run/secrets/password >/dev/null 2>&1; then
  echo "backup-test: ERROR: Produktion akzeptiert lokales Backup-Ziel" >&2
  exit 1
fi
if docker run --rm \
  -v "$root:/workspace:ro" \
  -v "$password_file:/run/secrets/password:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/backup/safety.py restore \
  --source-project "$source_project" \
  --target-project "$target_project" \
  --repository "$repository" \
  --password-file /run/secrets/password \
  --confirm RESTORE:irgendwo \
  --allow-local-test >/dev/null 2>&1; then
  echo "backup-test: ERROR: unklare Restore-Bestätigung wurde akzeptiert" >&2
  exit 1
fi

source_compose --profile dev-mail down --volumes --remove-orphans
restore_started=$(date +%s)
LEONAID_HTTP_PORT="$target_http_port" \
  LEONAID_HTTPS_PORT="$target_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_BACKUP_SOURCE_PROJECT="$source_project" \
  LEONAID_RESTORE_PROJECT="$target_project" \
  LEONAID_RESTORE_CONFIRM="RESTORE:$target_project" \
  LEONAID_BACKUP_REPOSITORY="$repository" \
  LEONAID_BACKUP_PASSWORD_FILE="$password_file" \
  LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
  LEONAID_RESTORE_START_APP=false \
  /bin/sh "$root/tools/backup/restore.sh" "$root"

target_compose build api public pwa web
target_compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env "TWENTY_DATABASE_URL=postgresql://twenty:${twenty_password}@twenty-postgres:5432/default" \
  --env PYTHONPATH=/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --volume "${target_project}_twenty-server-data:/twenty-storage:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/backup/inventory.py capture \
  --output /proof/after.json \
  --twenty-storage /twenty-storage
target_compose run --rm --no-deps \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/backup/inventory.py compare \
  --before /proof/before.json \
  --after /proof/after.json

target_compose --profile dev-mail up --detach --wait --wait-timeout 420
target_compose --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --entrypoint python \
  api /repo/tools/seed/golden.py snapshot \
  /repo/tests/fixtures/golden/v1 \
  --output /proof/restored-golden.json
docker run --rm \
  -v "$root:/workspace:ro" \
  -v "$proof:/proof:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/seed/verify_snapshot.py golden \
  /proof/restored-golden.json \
  /workspace/tests/fixtures/golden/v1

docker run --rm \
  --network "${target_project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof \
  --env KLARA_SESSION=poc101-10000000-0000-4000-8000-000000000002-server-session-token-value \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  tests/e2e/backup_restore.spec.mjs \
  --browser=chromium \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

restore_verified=$(date +%s)
rpo_seconds=$((backup_finished - recovery_checkpoint))
rto_seconds=$((restore_verified - restore_started))
[ "$rpo_seconds" -le 86400 ] || {
  echo "backup-test: ERROR: RPO-Ziel von 24 Stunden verfehlt" >&2
  exit 1
}
[ "$rto_seconds" -le 7200 ] || {
  echo "backup-test: ERROR: RTO-Ziel von 2 Stunden verfehlt" >&2
  exit 1
}
docker run --rm \
  -e "RPO_SECONDS=$rpo_seconds" \
  -e "RTO_SECONDS=$rto_seconds" \
  -v "$proof:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import json,os,pathlib
pathlib.Path("/proof/recovery-report.json").write_text(json.dumps({
  "schemaVersion":1,
  "rpoTargetSeconds":86400,
  "rpoMeasuredSeconds":int(os.environ["RPO_SECONDS"]),
  "rtoTargetSeconds":7200,
  "rtoMeasuredSeconds":int(os.environ["RTO_SECONDS"]),
  "result":"passed",
},sort_keys=True,indent=2)+"\n")'

mkdir -p "$artifact_directory"
cp "$proof/backup-restored-admin.png" \
  "$proof/recovery-report.json" \
  "$proof/before.json" \
  "$proof/after.json" \
  "$artifact_directory/"

echo "backup-test: OK: verschlüsselter externer Zielvertrag, vollständiger"
echo "backup-test:     Fresh-Volume-Restore, PDF-SHAs, Sitzungen, Audit,"
echo "backup-test:     Outbox, Twenty und RPO=$rpo_seconds s/RTO=$rto_seconds s bewiesen"
