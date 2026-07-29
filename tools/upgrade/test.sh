#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

source_project=${LEONAID_UPGRADE_TEST_PROJECT:-leonaid-poc113-upgrade}
rollback_project=${LEONAID_UPGRADE_ROLLBACK_PROJECT:-leonaid-restore-poc113-rollback}
source_http_port=${LEONAID_UPGRADE_TEST_PORT:-18133}
source_https_port=${LEONAID_UPGRADE_TEST_HTTPS_PORT:-18493}
rollback_http_port=${LEONAID_UPGRADE_ROLLBACK_PORT:-18134}
rollback_https_port=${LEONAID_UPGRADE_ROLLBACK_HTTPS_PORT:-18494}
compose_file="$root/infra/compose/compose.yml"
source_overlay="$root/infra/upgrade/compose.source.yml"
rollback_network_overlay="$root/infra/upgrade/compose.rollback-network.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
repository="$proof/repository"
password_file="$proof/restic-password"
artifact_directory=${LEONAID_UPGRADE_ARTIFACT_DIR:-"$root/.artifacts/poc113"}
integration_key=""
release_commit=$(git -C "$root" rev-parse HEAD)
release_ledger="$proof/release-ledger.jsonl"
release_v1="$proof/release-v1.json"
release_v2="$proof/release-v2.json"

source_old() {
  LEONAID_HTTP_PORT="$source_http_port" \
    LEONAID_HTTPS_PORT="$source_https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$source_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$source_overlay" \
      "$@"
}

source_target() {
  LEONAID_HTTP_PORT="$source_http_port" \
    LEONAID_HTTPS_PORT="$source_https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$source_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      "$@"
}

rollback_old() {
  LEONAID_HTTP_PORT="$rollback_http_port" \
    LEONAID_HTTPS_PORT="$rollback_https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$rollback_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$source_overlay" \
      --file "$rollback_network_overlay" \
      "$@"
}

rollback_target() {
  LEONAID_HTTP_PORT="$rollback_http_port" \
    LEONAID_HTTPS_PORT="$rollback_https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    docker compose \
      --project-name "$rollback_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$rollback_network_overlay" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    mkdir -p "$artifact_directory/failures"
    cp "$proof"/twenty-*.log "$artifact_directory/failures/" \
      >/dev/null 2>&1 || true
    echo "upgrade-test: Diagnose der fehlgeschlagenen Services:" >&2
    source_target ps --all >&2 || true
    rollback_target ps --all >&2 || true
    source_target logs --no-color --tail=260 \
      api core-postgres rustfs twenty-postgres twenty-server \
      twenty-worker proxy >&2 || true
    rollback_target logs --no-color --tail=260 \
      api core-postgres rustfs twenty-postgres twenty-server \
      twenty-worker proxy >&2 || true
  fi
  rollback_target --profile dev-mail down \
    --volumes --remove-orphans >/dev/null 2>&1 || true
  if [ "${LEONAID_UPGRADE_KEEP:-false}" != "true" ] || [ "$status" -ne 0 ]; then
    source_target --profile dev-mail down \
      --volumes --remove-orphans >/dev/null 2>&1 || true
  else
    echo "upgrade-test: Zielversion bleibt sichtbar unter http://127.0.0.1:$source_http_port/admin/"
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

fail() {
  echo "upgrade-test: ERROR: $*" >&2
  exit 1
}

[ -f "$env_file" ] || fail ".env.local fehlt; zuerst ./leonaid bootstrap"

verify_image() {
  container=$1
  expected=$2
  actual=$(docker inspect --format '{{ .Config.Image }}' "$container")
  [ "$actual" = "$expected" ] ||
    fail "$container läuft mit $actual statt $expected"
}

create_release_manifest() {
  release_id=$1
  version=$2
  twenty_image=$3
  rustfs_image=$4
  output=$5
  images="$proof/images-$release_id.json"
  api_id=$(docker image inspect --format '{{.Id}}' "${source_project}-api:latest")
  web_id=$(docker image inspect --format '{{.Id}}' "${source_project}-web:latest")
  pwa_id=$(docker image inspect --format '{{.Id}}' "${source_project}-pwa:latest")
  public_id=$(docker image inspect --format '{{.Id}}' "${source_project}-public:latest")
  docker run --rm \
    --env "API_IMAGE=$api_id" \
    --env "WEB_IMAGE=$web_id" \
    --env "PWA_IMAGE=$pwa_id" \
    --env "PUBLIC_IMAGE=$public_id" \
    --env "TWENTY_RELEASE_IMAGE=$twenty_image" \
    --env "RUSTFS_RELEASE_IMAGE=$rustfs_image" \
    --env "POSTGRES_RELEASE_IMAGE=$POSTGRES_IMAGE" \
    --env "REDIS_RELEASE_IMAGE=$REDIS_IMAGE" \
    --env "CADDY_RELEASE_IMAGE=$CADDY_IMAGE" \
    --env "IMAGE_OUTPUT=/proof/$(basename "$images")" \
    --volume "$proof:/proof" \
    "$PYTHON_IMAGE" \
    python -c 'import json,os,pathlib
pathlib.Path(os.environ["IMAGE_OUTPUT"]).write_text(json.dumps({
  "api":os.environ["API_IMAGE"],
  "worker":os.environ["API_IMAGE"],
  "web":os.environ["WEB_IMAGE"],
  "pwa":os.environ["PWA_IMAGE"],
  "public":os.environ["PUBLIC_IMAGE"],
  "twenty-server":os.environ["TWENTY_RELEASE_IMAGE"],
  "twenty-worker":os.environ["TWENTY_RELEASE_IMAGE"],
  "rustfs":os.environ["RUSTFS_RELEASE_IMAGE"],
  "core-postgres":os.environ["POSTGRES_RELEASE_IMAGE"],
  "twenty-postgres":os.environ["POSTGRES_RELEASE_IMAGE"],
  "twenty-redis":os.environ["REDIS_RELEASE_IMAGE"],
  "proxy":os.environ["CADDY_RELEASE_IMAGE"]
},sort_keys=True)+"\n",encoding="utf-8")'
  docker run --rm \
    --env PYTHONPATH=/workspace \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    "$PYTHON_IMAGE" \
    python tools/pilot_release/manifest.py create \
      --root /workspace \
      --release-id "$release_id" \
      --version "$version" \
      --git-commit "$release_commit" \
      --deployment-mode test \
      --images "/proof/$(basename "$images")" \
      --output "/proof/$(basename "$output")"
}

record_release_event() {
  manifest=$1
  event=$2
  result=$3
  evidence_id=$4
  occurred_at=$5
  docker run --rm \
    --env PYTHONPATH=/workspace \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    "$PYTHON_IMAGE" \
    python tools/pilot_release/promotion.py \
      --manifest "/proof/$(basename "$manifest")" \
      --ledger /proof/release-ledger.jsonl \
      --event "$event" \
      --result "$result" \
      --evidence-id "$evidence_id" \
      --occurred-at "$occurred_at"
}

run_plan_gate() {
  docker run --rm \
    -v "$root:/workspace:ro" \
    -w /workspace \
    "$PYTHON_IMAGE" \
    python tools/upgrade/validate_plan.py \
    infra/upgrade/compatibility-matrix.json \
    infra/locks/external-systems.lock
  cp "$root/infra/upgrade/compatibility-matrix.json" "$proof/invalid-matrix.json"
  docker run --rm \
    -v "$proof:/proof" \
    "$PYTHON_IMAGE" \
    python -c 'import json,pathlib
p=pathlib.Path("/proof/invalid-matrix.json")
v=json.loads(p.read_text())
v["components"][0]["releaseNotes"]=[]
p.write_text(json.dumps(v))'
  if docker run --rm \
    -v "$root:/workspace:ro" \
    -v "$proof:/proof:ro" \
    -w /workspace \
    "$PYTHON_IMAGE" \
    python tools/upgrade/validate_plan.py \
    /proof/invalid-matrix.json \
    infra/locks/external-systems.lock >/dev/null 2>&1; then
    fail "Upgradeplan ohne Release Notes wurde akzeptiert"
  fi
}

run_dashboard_contract() {
  mode=$1
  case "$mode" in
    source) runner=source_target ;;
    rollback) runner=rollback_target ;;
    *) fail "Unbekannter Contract-Modus: $mode" ;;
  esac
  $runner run --rm --no-deps \
    --env-from-file "$env_file" \
    --env API_BASE_URL=http://api:8000 \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --workdir /repo \
    --entrypoint python \
    api tools/dashboard/contract.py
}

run_maintenance_contract() {
  mode=$1
  state=$2
  case "$mode" in
    source) runner=source_target ;;
    rollback) runner=rollback_target ;;
    *) fail "Unbekannter Wartungsmodus: $mode" ;;
  esac
  $runner run --rm --no-deps \
    --env-from-file "$env_file" \
    --env API_BASE_URL=http://api:8000 \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --workdir /repo \
    --entrypoint python \
    api tools/upgrade/contract.py "$state"
}

run_twenty_upgrade() {
  mode=$1
  label=$2
  case "$mode" in
    source) runner=source_target ;;
    rollback) runner=rollback_target ;;
    *) fail "Unbekannter Twenty-Upgrade-Modus: $mode" ;;
  esac
  # Twenty's supported entrypoint establishes any instance-level schema
  # prerequisites before it invokes the workspace upgrade. Let that bootstrap
  # finish once, then repeat the documented upgrade command with a strict exit
  # code instead of accepting the entrypoint's warning-and-continue behavior.
  $runner up --detach --force-recreate --wait --wait-timeout 420 \
    twenty-server
  if $runner logs --no-color twenty-server \
    | grep -F "Warning: Upgrade completed with errors" >/dev/null; then
    fail "Twenty-Entrypoint meldet einen fehlgeschlagenen Upgrade-Lauf: $label"
  fi
  $runner stop twenty-server
  if ! $runner run --rm --no-deps \
    --entrypoint yarn \
    twenty-server command:prod run-instance-commands \
    >"$proof/twenty-instance-upgrade-$label.log" 2>&1; then
    tail -n 120 "$proof/twenty-instance-upgrade-$label.log" >&2
    fail "Twenty-Instance-Upgrade ist fehlgeschlagen: $label"
  fi
  if ! $runner run --rm --no-deps \
    --entrypoint yarn \
    twenty-server command:prod upgrade \
    >"$proof/twenty-upgrade-$label.log" 2>&1; then
    tail -n 120 "$proof/twenty-upgrade-$label.log" >&2
    fail "Twenty-Upgrade-Command ist fehlgeschlagen: $label"
  fi
  $runner up --detach --force-recreate --wait --wait-timeout 420 \
    twenty-server twenty-worker
  $runner exec -T twenty-postgres psql \
    --username "${TWENTY_POSTGRES_USER:-twenty}" \
    --dbname "${TWENTY_POSTGRES_DB:-default}" \
    --tuples-only \
    --no-align \
    --command "SELECT count(*) FROM information_schema.columns WHERE table_schema='core' AND table_name='keyValuePair' AND column_name='applicationId'" \
    | grep -Fx "1" >/dev/null ||
    fail "Twenty-Zielschema fehlt nach Upgrade-Command: $label"
  echo "upgrade-test: Twenty-Upgrade-Command und Zielschema OK: $label"
}

snapshot_and_verify() {
  mode=$1
  name=$2
  expectation=$3
  case "$mode" in
    source) runner=source_target ;;
    rollback) runner=rollback_target ;;
    *) fail "Unbekannter Snapshot-Modus: $mode" ;;
  esac
  $runner --profile dev-mail run --rm --no-deps \
    --env-from-file "$env_file" \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --entrypoint python \
    api /repo/tools/seed/golden.py snapshot \
    /repo/tests/fixtures/golden/v1 \
    --output "/proof/$name.json"
  docker run --rm \
    -v "$root:/workspace:ro" \
    -v "$proof:/proof:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/seed/verify_snapshot.py "$expectation" \
    "/proof/$name.json" \
    /workspace/tests/fixtures/golden/v1
}

run_e2e() {
  project=$1
  phase=$2
  case "$phase" in
    before)
      expected_order_count=6
      expected_quantity="25 Boxen · 600 Stück"
      expected_invoiced="504,00 €"
      expected_outstanding="360,00 €"
      ;;
    after|rollback)
      expected_order_count=12
      expected_quantity="34 Boxen · 816 Stück"
      expected_invoiced="720,00 €"
      expected_outstanding="360,00 €"
      ;;
    *) fail "Unbekannte Browser-Smoke-Phase: $phase" ;;
  esac
  docker run --rm \
    --network "${project}_edge" \
    --env CI=1 \
    --env HOME=/tmp \
    --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof \
    --env "LEONAID_UPGRADE_PHASE=$phase" \
    --env "LEONAID_UPGRADE_EXPECTED_ORDER_COUNT=$expected_order_count" \
    --env "LEONAID_UPGRADE_EXPECTED_QUANTITY=$expected_quantity" \
    --env "LEONAID_UPGRADE_EXPECTED_INVOICED=$expected_invoiced" \
    --env "LEONAID_UPGRADE_EXPECTED_OUTSTANDING=$expected_outstanding" \
    --env KLARA_SESSION=poc101-10000000-0000-4000-8000-000000000002-server-session-token-value \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test \
    tests/e2e/upgrade.spec.mjs \
    --browser=chromium \
    --output="/proof/test-results-$phase" \
    --trace=retain-on-failure \
    --reporter=line
  [ -s "$proof/upgrade-$phase.png" ] ||
    fail "Browsernachweis fehlt: upgrade-$phase.png"
}

run_full_golden_journey() {
  mode=$1
  project=$2
  phase=$3
  round_name=$4
  case "$mode" in
    source) runner=source_target ;;
    rollback) runner=rollback_target ;;
    *) fail "Unbekannter Golden-Journey-Modus: $mode" ;;
  esac
  artifact_path="journey-$phase"
  session_file="sessions-$phase.env"
  summary_file="journey-$phase.json"
  normalized_file="journey-$phase.normalized.json"
  mkdir -p "$proof/$artifact_path"

  $runner run --rm --no-deps \
    --user "$(id -u):$(id -g)" \
    --env-from-file "$env_file" \
    --env API_BASE_URL=http://api:8000 \
    --env MAIL_TEST_API_URL=http://mailpit:8025/mail \
    --env TWENTY_BASE_URL=http://twenty-server:3000 \
    --env TWENTY_INTEGRATION_API_KEY="$integration_key" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api tools/golden_journey/contract.py \
    prepare-sessions "$round_name" "/proof/$session_file"

  session_mode=$(stat -c '%a' "$proof/$session_file" 2>/dev/null || \
    stat -f '%Lp' "$proof/$session_file")
  [ "$session_mode" = "600" ] ||
    fail "Golden-Journey-Sitzungsdatei ist nicht Modus 600: $phase"

  docker run --rm \
    --network "${project}_edge" \
    --env CI=1 \
    --env HOME=/tmp \
    --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_MAILPIT_URL=http://mailpit:8025/mail \
    --env LEONAID_E2E_ARTIFACT_DIR="/proof/$artifact_path" \
    --env LEONAID_GOLDEN_JOURNEY_ROUND="$round_name" \
    --env-file "$proof/$session_file" \
    --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" \
    --workdir /workspace \
    --user "$(id -u):$(id -g)" \
    "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test \
    --config=tests/e2e/pwa.config.mjs \
    golden-journey.spec.mjs \
    --project=chromium-390 \
    --project=firefox-390 \
    --project=webkit-390 \
    --output="/proof/results-journey-$phase" \
    --trace=retain-on-failure \
    --reporter=line

  $runner run --rm --no-deps \
    --user "$(id -u):$(id -g)" \
    --env-from-file "$env_file" \
    --env API_BASE_URL=http://api:8000 \
    --env MAIL_TEST_API_URL=http://mailpit:8025/mail \
    --env TWENTY_BASE_URL=http://twenty-server:3000 \
    --env TWENTY_INTEGRATION_API_KEY="$integration_key" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api tools/golden_journey/contract.py \
    verify "$round_name" "/proof/$artifact_path" \
    "/proof/$summary_file" "/proof/$normalized_file"

  $runner run --rm --no-deps \
    --env-from-file "$env_file" \
    --entrypoint python \
    api -c 'import httpx
response=httpx.delete("http://mailpit:8025/mail/api/v1/messages",timeout=20)
response.raise_for_status()'

  echo "upgrade-test: vollständige Golden Journey OK: $phase ($round_name)"
}

restore_source_version() {
  LEONAID_HTTP_PORT="$rollback_http_port" \
    LEONAID_HTTPS_PORT="$rollback_https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    LEONAID_BACKUP_SOURCE_PROJECT="$source_project" \
    LEONAID_RESTORE_PROJECT="$rollback_project" \
    LEONAID_RESTORE_CONFIRM="RESTORE:$rollback_project" \
    LEONAID_BACKUP_REPOSITORY="$repository" \
    LEONAID_BACKUP_PASSWORD_FILE="$password_file" \
    LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
    LEONAID_RESTORE_START_APP=false \
    LEONAID_RESTORE_COMPOSE_OVERLAY="$source_overlay" \
    LEONAID_RESTORE_COMPOSE_OVERLAY_SECONDARY="$rollback_network_overlay" \
    /bin/sh "$root/tools/backup/restore.sh" "$root"
}

source_old --profile dev-mail down \
  --volumes --remove-orphans >/dev/null 2>&1 || true
rollback_old --profile dev-mail down \
  --volumes --remove-orphans >/dev/null 2>&1 || true
mkdir -p "$repository"
docker run --rm \
  -v "$proof:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import pathlib,secrets
pathlib.Path("/proof/restic-password").write_text(secrets.token_urlsafe(48)+"\n")'
chmod 600 "$password_file"

run_plan_gate
source_old build api public pwa web
create_release_manifest \
  pilot-release-v1 1.0.0 \
  "$TWENTY_UPGRADE_SOURCE_IMAGE" "$RUSTFS_UPGRADE_SOURCE_IMAGE" \
  "$release_v1"
create_release_manifest \
  pilot-release-v2 2.0.0 \
  "$TWENTY_IMAGE" "$RUSTFS_IMAGE" \
  "$release_v2"
record_release_event \
  "$release_v1" staging_started passed PILOT-043-STAGING-V1 \
  2026-07-28T08:00:00Z
source_old --profile dev-mail up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker
verify_image "${source_project}-twenty-server-1" "$TWENTY_UPGRADE_SOURCE_IMAGE"
verify_image "${source_project}-rustfs-1" "$RUSTFS_UPGRADE_SOURCE_IMAGE"

source_old run --rm --no-deps \
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
[ "${#integration_key}" -ge 32 ] || fail "eingeschränkter Twenty-Key fehlt"

source_old up --detach --wait --wait-timeout 420 api
/bin/sh "$root/tools/typst/render_golden.sh" \
  "$root" "$proof/pdfs" "${source_project}-api"
source_old --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --volume "$root:/repo:ro" \
  --volume "$proof/pdfs:/proof/pdfs:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py seed \
  /repo/tests/fixtures/golden/v1 \
  /proof/pdfs
run_dashboard_contract source
snapshot_and_verify source pre-upgrade golden
source_old up --detach --wait --wait-timeout 420 worker public pwa web proxy
run_e2e "$source_project" before
run_full_golden_journey source "$source_project" before round-1
record_release_event \
  "$release_v1" staging_verified passed PILOT-043-STAGING-V1 \
  2026-07-28T08:10:00Z
record_release_event \
  "$release_v2" staging_started passed PILOT-043-STAGING-V2 \
  2026-07-28T08:20:00Z

LEONAID_COMPOSE_PROJECT="$source_project" \
  LEONAID_HTTP_PORT="$source_http_port" \
  LEONAID_HTTPS_PORT="$source_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_BACKUP_REPOSITORY="$repository" \
  LEONAID_BACKUP_PASSWORD_FILE="$password_file" \
  LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
  /bin/sh "$root/tools/backup/backup.sh" "$root"

LEONAID_COMPOSE_PROJECT="$source_project" \
  LEONAID_HTTP_PORT="$source_http_port" \
  LEONAID_HTTPS_PORT="$source_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  /bin/sh "$root/infra/upgrade/maintenance.sh" enable "$root"
run_maintenance_contract source maintenance
running_writers=$(source_target ps --services --filter status=running)
for writer in worker twenty-server twenty-worker; do
  if echo "$running_writers" | grep -Fx "$writer" >/dev/null; then
    fail "Writer läuft im Wartungsmodus weiter: $writer"
  fi
done

source_target up --detach --force-recreate --wait --wait-timeout 420 \
  rustfs
run_twenty_upgrade source primary
verify_image "${source_project}-twenty-server-1" "$TWENTY_IMAGE"
verify_image "${source_project}-rustfs-1" "$RUSTFS_IMAGE"
LEONAID_COMPOSE_PROJECT="$source_project" \
  LEONAID_HTTP_PORT="$source_http_port" \
  LEONAID_HTTPS_PORT="$source_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  /bin/sh "$root/infra/upgrade/maintenance.sh" disable "$root"
source_target --profile dev-mail up --detach --wait --wait-timeout 420
run_maintenance_contract source available
run_dashboard_contract source
snapshot_and_verify source post-upgrade golden
run_e2e "$source_project" after
run_full_golden_journey source "$source_project" after round-2
record_release_event \
  "$release_v2" staging_verified passed PILOT-043-STAGING-V2 \
  2026-07-28T08:40:00Z

restore_source_version
rollback_old build api public pwa web
rollback_old --profile dev-mail up --detach --wait --wait-timeout 420
run_dashboard_contract rollback
snapshot_and_verify rollback failure-clone-before golden

record_release_event \
  "$release_v2" production_started passed PILOT-043-PRODUCTION-ATTEMPT-1 \
  2026-07-28T09:00:00Z
LEONAID_COMPOSE_PROJECT="$rollback_project" \
  LEONAID_HTTP_PORT="$rollback_http_port" \
  LEONAID_HTTPS_PORT="$rollback_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_MAINTENANCE_COMPOSE_OVERLAY="$rollback_network_overlay" \
  /bin/sh "$root/infra/upgrade/maintenance.sh" enable "$root"
if rollback_target run --rm --no-deps \
  --entrypoint uv \
  api run --frozen --no-sync alembic upgrade pilot_missing_revision \
  >"$proof/core-migration-failure.log" 2>&1; then
  fail "Absichtlich ungültige Core-Migration wurde akzeptiert"
fi
run_maintenance_contract rollback maintenance
record_release_event \
  "$release_v2" production_failed failed PILOT-043-MIGRATION-FAILURE \
  2026-07-28T09:01:00Z

rollback_target --profile dev-mail down --volumes --remove-orphans
record_release_event \
  "$release_v2" rollback_started passed PILOT-043-MIGRATION-ROLLBACK \
  2026-07-28T09:02:00Z
restore_source_version
rollback_old --profile dev-mail up --detach --wait --wait-timeout 420
run_dashboard_contract rollback
snapshot_and_verify rollback migration-failure-restored golden
record_release_event \
  "$release_v2" rollback_verified passed PILOT-043-MIGRATION-ROLLBACK \
  2026-07-28T09:10:00Z

record_release_event \
  "$release_v2" production_started passed PILOT-043-PRODUCTION-ATTEMPT-2 \
  2026-07-28T09:20:00Z
LEONAID_COMPOSE_PROJECT="$rollback_project" \
  LEONAID_HTTP_PORT="$rollback_http_port" \
  LEONAID_HTTPS_PORT="$rollback_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_MAINTENANCE_COMPOSE_OVERLAY="$rollback_network_overlay" \
  /bin/sh "$root/infra/upgrade/maintenance.sh" enable "$root"
rollback_target up --detach --force-recreate --wait --wait-timeout 420 \
  rustfs
run_twenty_upgrade rollback failure-clone
LEONAID_COMPOSE_PROJECT="$rollback_project" \
  LEONAID_HTTP_PORT="$rollback_http_port" \
  LEONAID_HTTPS_PORT="$rollback_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_MAINTENANCE_COMPOSE_OVERLAY="$rollback_network_overlay" \
  /bin/sh "$root/infra/upgrade/maintenance.sh" disable "$root"
rollback_target --profile dev-mail up --detach --wait --wait-timeout 420
run_dashboard_contract rollback
snapshot_and_verify rollback production-v2 golden
record_release_event \
  "$release_v2" production_verified passed PILOT-043-PRODUCTION-V2 \
  2026-07-28T09:40:00Z
rollback_target --profile dev-mail run --rm --no-deps \
  --env-from-file "$env_file" \
  --env MAIL_SMTP_HOST=mailpit \
  --env MAIL_SMTP_PORT=1025 \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py mutate \
  /repo/tests/fixtures/golden/v1
snapshot_and_verify rollback failed-upgrade mutated
if docker run --rm \
  -v "$root:/workspace:ro" \
  -v "$proof:/proof:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/seed/verify_snapshot.py golden \
  /proof/failed-upgrade.json \
  /workspace/tests/fixtures/golden/v1 >/dev/null 2>&1; then
  fail "Absichtlich defektes Upgrade bestand den Golden-Contract"
fi
record_release_event \
  "$release_v2" production_failed failed PILOT-043-POST-SMOKE-FAILURE \
  2026-07-28T09:41:00Z

rollback_target --profile dev-mail down --volumes --remove-orphans
record_release_event \
  "$release_v2" rollback_started passed PILOT-043-POST-SMOKE-ROLLBACK \
  2026-07-28T09:42:00Z
restore_source_version
rollback_old build api public pwa web
rollback_old --profile dev-mail up --detach --wait --wait-timeout 420
run_dashboard_contract rollback
snapshot_and_verify rollback rollback-restored golden
run_e2e "$rollback_project" rollback
run_full_golden_journey rollback "$rollback_project" rollback round-2
if ! cmp -s \
  "$proof/journey-after.normalized.json" \
  "$proof/journey-rollback.normalized.json"; then
  diff -u \
    "$proof/journey-after.normalized.json" \
    "$proof/journey-rollback.normalized.json" >&2 || true
  fail "Golden Journey ist nach dem Rollback nicht fachlich identisch"
fi
record_release_event \
  "$release_v2" rollback_verified passed PILOT-043-POST-SMOKE-ROLLBACK \
  2026-07-28T09:50:00Z

mkdir -p "$artifact_directory"
cp "$proof"/upgrade-before.png \
  "$proof"/upgrade-after.png \
  "$proof"/upgrade-rollback.png \
  "$proof"/pre-upgrade.json \
  "$proof"/post-upgrade.json \
  "$proof"/migration-failure-restored.json \
  "$proof"/production-v2.json \
  "$proof"/failed-upgrade.json \
    "$proof"/rollback-restored.json \
    "$proof"/core-migration-failure.log \
    "$proof"/release-v1.json \
    "$proof"/release-v2.json \
    "$proof"/release-ledger.jsonl \
    "$proof"/twenty-instance-upgrade-primary.log \
  "$proof"/twenty-instance-upgrade-failure-clone.log \
  "$proof"/twenty-upgrade-primary.log \
  "$proof"/twenty-upgrade-failure-clone.log \
  "$proof"/journey-before.json \
  "$proof"/journey-before.normalized.json \
  "$proof"/journey-after.json \
  "$proof"/journey-after.normalized.json \
  "$proof"/journey-rollback.json \
  "$proof"/journey-rollback.normalized.json \
  "$root/infra/upgrade/compatibility-matrix.json" \
  "$artifact_directory/"
cp -R \
  "$proof"/journey-before \
  "$proof"/journey-after \
  "$proof"/journey-rollback \
  "$artifact_directory/"
docker run --rm \
  -v "$artifact_directory:/artifacts" \
  "$PYTHON_IMAGE" \
  python -c 'import json,pathlib
pathlib.Path("/artifacts/result.json").write_text(json.dumps({
  "schemaVersion":1,
  "result":"passed",
  "source":{"twenty":"2.23.2","rustfs":"1.0.0-beta.10"},
  "target":{"twenty":"2.24.0","rustfs":"1.0.0-beta.11"},
  "preContract":"passed",
  "preE2e":"passed",
  "preGoldenJourney":"passed",
  "maintenanceWriteBoundary":"passed",
  "postContract":"passed",
  "postE2e":"passed",
  "postGoldenJourney":"passed",
  "sameManifestPromotion":"passed",
  "coreMigrationFailureDetected":"passed",
  "failedUpgradeDetected":"passed",
  "backupRollback":"passed",
  "rollbackGoldenJourney":"passed",
  "rollbackJourneyEquivalent":"passed",
  "releaseLedger":"passed"
},sort_keys=True,indent=2)+"\n")'

echo "upgrade-test: OK: reale Twenty- und RustFS-Upgrades,"
echo "upgrade-test:     Wartungsgrenze, Contract/E2E vor und nach dem Upgrade"
echo "upgrade-test:     vollständige Golden Journeys vor/nach Upgrade und Rollback"
echo "upgrade-test:     sowie Manifest-Promotion, Migrationsfehler und Recovery bewiesen"
