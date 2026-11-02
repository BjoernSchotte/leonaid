#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
source_project=${LEONAID_UPGRADE_TEST_PROJECT:-leonaid-poc113-upgrade}-$suffix
rollback_project=${LEONAID_UPGRADE_ROLLBACK_PROJECT:-leonaid-restore-poc113-rollback}-$suffix
source_owned=false
rollback_owned=false
restore_generation=0
source_http_port=${LEONAID_UPGRADE_TEST_PORT:-18133}
source_https_port=${LEONAID_UPGRADE_TEST_HTTPS_PORT:-18493}
rollback_http_port=${LEONAID_UPGRADE_ROLLBACK_PORT:-18134}
rollback_https_port=${LEONAID_UPGRADE_ROLLBACK_HTTPS_PORT:-18494}
compose_file="$root/infra/compose/compose.yml"
source_overlay="$root/infra/upgrade/compose.source.yml"
rollback_network_template="$root/infra/upgrade/compose.rollback-network.yml"
env_file="$root/.env.local"
mkdir -p "$root/.artifacts"
proof=$(mktemp -d "$root/.artifacts/upgrade-regression.XXXXXX")
chmod 700 "$proof"
source_isolation="$proof/source.yml"
rollback_network_overlay="$proof/rollback.yml"
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
      --file "$source_isolation" \
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
      --file "$source_isolation" \
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

verify_cleanup() {
  checked_project=$1
  for inventory in containers volumes networks; do
    case "$inventory" in
      containers) remaining=$(docker ps -aq --filter "label=com.docker.compose.project=$checked_project") || return 1 ;;
      volumes) remaining=$(docker volume ls -q --filter "label=com.docker.compose.project=$checked_project") || return 1 ;;
      networks) remaining=$(docker network ls -q --filter "label=com.docker.compose.project=$checked_project") || return 1 ;;
    esac
    if [ -n "$remaining" ]; then
      echo "test-isolation: owned $inventory remain for $checked_project" >&2
      return 1
    fi
  done
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    if [ "$source_owned" = true ] || [ "$rollback_owned" = true ]; then
      mkdir -p "$artifact_directory/failures"
      cp "$proof"/twenty-*.log "$artifact_directory/failures/" >/dev/null 2>&1 || true
    fi
    echo "upgrade-test: Diagnose der fehlgeschlagenen eigenen Services:" >&2
    if [ "$source_owned" = true ]; then
      source_target ps --all >&2 || true
      source_target logs --no-color --tail=240 api core-postgres rustfs twenty-postgres twenty-server proxy >&2 || true
    fi
    if [ "$rollback_owned" = true ]; then
      rollback_target ps --all >&2 || true
      rollback_target logs --no-color --tail=240 api core-postgres rustfs twenty-postgres twenty-server proxy >&2 || true
    fi
  fi
  if [ "$rollback_owned" = true ]; then
    if ! rollback_target --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    if ! verify_cleanup "$rollback_project"; then status=1; fi
  fi
  if [ "$source_owned" = true ]; then
    if [ "${LEONAID_UPGRADE_KEEP:-false}" != "true" ] || [ "$status" -ne 0 ]; then
      if ! source_target --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
      if ! verify_cleanup "$source_project"; then status=1; fi
    else
      echo "upgrade-test: Owned source project retained stopped without host ports: $source_project"
    fi
  fi
  if [ "$status" -eq 0 ] && [ "$source_owned" = true ] && [ "${LEONAID_UPGRADE_KEEP:-false}" != "true" ]; then
    echo "test-isolation: $source_project and $rollback_project passed and owned resources were removed"
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
  queue_image=$5
  postgres_image=$6
  output=$7
  images="$proof/images-$release_id.json"
  api_id=$(docker image inspect --format '{{.Id}}' "${source_project}-api:latest")
  web_id=$(docker image inspect --format '{{.Id}}' "${source_project}-web:latest")
  pwa_id=$(docker image inspect --format '{{.Id}}' "${source_project}-pwa:latest")
  public_id=$(docker image inspect --format '{{.Id}}' "${source_project}-public:latest")
  proxy_id=$(docker image inspect --format '{{.Id}}' "${source_project}-proxy:latest")
  survey_validator_id=$(docker image inspect --format '{{.Id}}' "${source_project}-survey-validator:latest")
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    --env "API_IMAGE=$api_id" \
    --env "WEB_IMAGE=$web_id" \
    --env "PWA_IMAGE=$pwa_id" \
    --env "PUBLIC_IMAGE=$public_id" \
    --env "SURVEY_VALIDATOR_IMAGE=$survey_validator_id" \
    --env "TWENTY_RELEASE_IMAGE=$twenty_image" \
    --env "RUSTFS_RELEASE_IMAGE=$rustfs_image" \
    --env "POSTGRES_RELEASE_IMAGE=$postgres_image" \
    --env "REDIS_RELEASE_IMAGE=$queue_image" \
    --env "CADDY_RELEASE_IMAGE=$proxy_id" \
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
  "survey-validator":os.environ["SURVEY_VALIDATOR_IMAGE"],
  "twenty-server":os.environ["TWENTY_RELEASE_IMAGE"],
  "twenty-worker":os.environ["TWENTY_RELEASE_IMAGE"],
  "rustfs":os.environ["RUSTFS_RELEASE_IMAGE"],
  "core-postgres":os.environ["POSTGRES_RELEASE_IMAGE"],
  "twenty-postgres":os.environ["POSTGRES_RELEASE_IMAGE"],
  "twenty-redis":os.environ["REDIS_RELEASE_IMAGE"],
  "proxy":os.environ["CADDY_RELEASE_IMAGE"]
},sort_keys=True)+"\n",encoding="utf-8")'
  docker run --rm \
    --user "$(id -u):$(id -g)" \
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
    --user "$(id -u):$(id -g)" \
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
    --user "$(id -u):$(id -g)" \
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
  $runner run --rm --user "$(id -u):$(id -g)" --no-deps \
    --env-from-file "$env_file" \
    --env API_BASE_URL=http://api:8000 \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --workdir /repo \
    --entrypoint python \
    api tools/dashboard/contract.py
  $runner run --rm --user "$(id -u):$(id -g)" --no-deps \
    --env-from-file "$env_file" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --workdir /repo \
    --entrypoint python \
    api tools/upgrade/survey_contract.py
}

run_maintenance_contract() {
  mode=$1
  state=$2
  case "$mode" in
    source) runner=source_target ;;
    rollback) runner=rollback_target ;;
    *) fail "Unbekannter Wartungsmodus: $mode" ;;
  esac
  $runner run --rm --user "$(id -u):$(id -g)" --no-deps \
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
  # Exactly two of three columns: keyValuePair.applicationId (since 2.24) and
  # userSession.country (2.54) exist, view.isCustom (dropped in 2.54) not.
  $runner exec -T twenty-postgres psql \
    --username "${TWENTY_POSTGRES_USER:-twenty}" \
    --dbname "${TWENTY_POSTGRES_DB:-default}" \
    --tuples-only \
    --no-align \
    --command "SELECT count(*) FROM information_schema.columns WHERE table_schema='core' AND ((table_name='keyValuePair' AND column_name='applicationId') OR (table_name='userSession' AND column_name='country') OR (table_name='view' AND column_name='isCustom'))" \
    | grep -Fx "2" >/dev/null ||
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
  $runner --profile dev-mail run --rm --user "$(id -u):$(id -g)" --no-deps \
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

# Hash every object version in RustFS; used around the RustFS image swap.
object_inventory() {
  runner=$1
  name=$2
  $runner run --rm --user "$(id -u):$(id -g)" --no-deps \
    --env-from-file "$env_file" \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --entrypoint python \
    api /repo/tools/upgrade/object_inventory.py "/proof/$name.json"
}

require_same_objects() {
  before=$1
  after=$2
  if ! cmp -s "$proof/$before.json" "$proof/$after.json"; then
    diff -u "$proof/$before.json" "$proof/$after.json" >&2 || true
    fail "RustFS upgrade changed stored object versions or bytes"
  fi
  echo "upgrade-test: RustFS upgrade preserved every object version and SHA-256"
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

# The old release ran Redis 7.4 (RDB format 12), which Valkey refuses to load.
# Prove that the old volume really has that format, then migrate it exactly
# like pilot-release does: drain with the old containers and reset.
migrate_queue_store() {
  migrated_project=$1
  docker exec "${migrated_project}-twenty-redis-1" redis-cli SAVE >/dev/null
  header=$(docker run --rm --network none \
    --volume "${migrated_project}_twenty-redis-data:/data:ro" \
    "$ALPINE_IMAGE" head -c 9 /data/dump.rdb)
  [ "$header" = REDIS0012 ] ||
    fail "old queue volume of $migrated_project is not a Redis 7.4 RDB: $header"
  state=$(LEONAID_COMPOSE_PROJECT="$migrated_project" \
    /bin/sh "$root/infra/upgrade/twenty-queue-store.sh" status "$root")
  [ "$state" = legacy-redis ] ||
    fail "queue store of $migrated_project not detected as Redis 7.4: $state"
  if LEONAID_COMPOSE_PROJECT="$migrated_project" \
    /bin/sh "$root/infra/upgrade/twenty-queue-store.sh" require-current "$root" \
    >/dev/null 2>&1; then
    fail "pilot-deploy guard accepted the Redis 7.4 queue store"
  fi
  LEONAID_COMPOSE_PROJECT="$migrated_project" \
    /bin/sh "$root/infra/upgrade/twenty-queue-store.sh" migrate "$root"
  state=$(LEONAID_COMPOSE_PROJECT="$migrated_project" \
    /bin/sh "$root/infra/upgrade/twenty-queue-store.sh" status "$root")
  [ "$state" = empty ] ||
    fail "queue store of $migrated_project not reset: $state"
}

verify_valkey() {
  checked_project=$1
  container="${checked_project}-twenty-redis-1"
  verify_image "$container" "$VALKEY_IMAGE"
  docker exec "$container" valkey-cli INFO server | tr -d '\r' |
    grep -Fx server_name:valkey >/dev/null ||
    fail "$container does not run Valkey"
  [ "$(docker inspect --format '{{.RestartCount}}' "$container")" = 0 ] ||
    fail "$container restarted on the migrated volume"
  docker exec "$container" valkey-cli CONFIG GET maxmemory-policy | tr -d '\r' |
    grep -Fx noeviction >/dev/null ||
    fail "$container lost maxmemory-policy noeviction"
  if docker logs "${checked_project}-twenty-worker-1" 2>&1 |
    grep -i -e 'eviction policy' -e 'minimum redis version' >/dev/null; then
    fail "twenty-worker warns about the Valkey store"
  fi
  state=$(LEONAID_COMPOSE_PROJECT="$checked_project" \
    /bin/sh "$root/infra/upgrade/twenty-queue-store.sh" status "$root")
  [ "$state" = valkey ] || fail "queue store of $checked_project is $state"
  echo "upgrade-test: Redis 7.4 queue volume migrated; Valkey runs without restarts: $checked_project"
}

verify_postgres() {
  checked_project=$1
  expected_version=${POSTGRES_IMAGE#*:}
  expected_version=${expected_version%%-*}
  for service in core-postgres twenty-postgres; do
    container="${checked_project}-${service}-1"
    verify_image "$container" "$POSTGRES_IMAGE"
    [ "$(docker inspect --format '{{.RestartCount}}' "$container")" = 0 ] ||
      fail "$container restarted on the data directory of the previous release"
    actual_version=$(docker exec "$container" sh -c \
      'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align --command "SHOW server_version"' |
      tr -d '\r' | cut -d ' ' -f 1)
    [ "$actual_version" = "$expected_version" ] ||
      fail "$container serves PostgreSQL $actual_version instead of $expected_version"
    # A libc/ICU change between Alpine releases must not leave a database
    # whose recorded collation version differs from the runtime library.
    mismatched=$(docker exec "$container" sh -c \
      'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align --command "SELECT datname FROM pg_database WHERE datallowconn AND datcollversion IS DISTINCT FROM pg_database_collation_actual_version(oid)"' |
      tr -d '\r')
    [ -z "$mismatched" ] ||
      fail "$container reports collation version mismatches: $mismatched"
    if docker logs "$container" 2>&1 | grep -i 'collation version mismatch' >/dev/null; then
      fail "$container logs a collation version mismatch"
    fi
  done
  echo "upgrade-test: PostgreSQL $expected_version runs on the previous data directories: $checked_project"
}

restore_source_version() {
  verify_cleanup "$rollback_project"
  restore_generation=$((restore_generation + 1))
  python3 "$root/tools/surveys/network_override.py" "$rollback_network_overlay"
  python3 - "$rollback_network_template" "$rollback_network_overlay" <<'PY_OVERLAY'
from pathlib import Path
import sys
original = Path(sys.argv[1]).read_text()
path = Path(sys.argv[2])
selected = path.read_text()
assert original.startswith("services:\n  proxy:\n")
original = original.replace("services:\n  proxy:\n", "services:\n  proxy:\n    ports: !reset []\n", 1)
path.write_text(original + selected[selected.index("networks:\n"):])
PY_OVERLAY
  rollback_owned=true
  rollback_old --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$rollback_project" "$rollback_network_overlay"
  LEONAID_HTTP_PORT="$rollback_http_port" \
    LEONAID_HTTPS_PORT="$rollback_https_port" \
    TWENTY_INTEGRATION_API_KEY="$integration_key" \
    LEONAID_BACKUP_SOURCE_PROJECT="$source_project" \
    LEONAID_RESTORE_PROJECT="$rollback_project" \
    LEONAID_RESTORE_CONFIRM="RESTORE:$rollback_project" \
    LEONAID_BACKUP_REPOSITORY="$repository" \
    LEONAID_BACKUP_PASSWORD_FILE="$password_file" \
    LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
    LEONAID_RESTORE_NETWORKS_PRERESERVED=true \
    LEONAID_RESTORE_START_APP=false \
    LEONAID_RESTORE_STATE_FILE="$proof/restore-state-$restore_generation.json" \
    LEONAID_RESTORE_COMPOSE_OVERLAY="$source_overlay" \
    LEONAID_RESTORE_COMPOSE_OVERLAY_SECONDARY="$rollback_network_overlay" \
    /bin/sh "$root/tools/backup/restore.sh" "$root"
}

# Refuse either occupied identity before acquiring any source resources.
for checked_project in "$source_project" "$rollback_project"; do
  existing=$(docker ps -aq --filter "label=com.docker.compose.project=$checked_project")
  [ -z "$existing" ]
  existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$checked_project")
  [ -z "$existing" ]
  existing=$(docker network ls -q --filter "label=com.docker.compose.project=$checked_project")
  [ -z "$existing" ]
done
python3 "$root/tools/surveys/network_override.py" "$source_isolation"
source_owned=true
source_old --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$source_project" "$source_isolation"
mkdir -p "$repository"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$proof:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import pathlib,secrets
pathlib.Path("/proof/restic-password").write_text(secrets.token_urlsafe(48)+"\n")'
chmod 600 "$password_file"

run_plan_gate
source_old build api public pwa web survey-validator proxy
create_release_manifest \
  pilot-release-v1 1.0.0 \
  "$TWENTY_UPGRADE_SOURCE_IMAGE" "$RUSTFS_UPGRADE_SOURCE_IMAGE" \
  "$REDIS_UPGRADE_SOURCE_IMAGE" "$POSTGRES_UPGRADE_SOURCE_IMAGE" "$release_v1"
create_release_manifest \
  pilot-release-v2 2.0.0 \
  "$TWENTY_IMAGE" "$RUSTFS_IMAGE" \
  "$VALKEY_IMAGE" "$POSTGRES_IMAGE" "$release_v2"
record_release_event \
  "$release_v1" staging_started passed PILOT-043-STAGING-V1 \
  2026-07-28T08:00:00Z
source_old --profile dev-mail up --detach --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker
verify_image "${source_project}-twenty-server-1" "$TWENTY_UPGRADE_SOURCE_IMAGE"
verify_image "${source_project}-rustfs-1" "$RUSTFS_UPGRADE_SOURCE_IMAGE"
verify_image "${source_project}-core-postgres-1" "$POSTGRES_UPGRADE_SOURCE_IMAGE"
verify_image "${source_project}-twenty-postgres-1" "$POSTGRES_UPGRADE_SOURCE_IMAGE"

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
source_old --profile dev-mail run --rm --user "$(id -u):$(id -g)" --no-deps \
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
  LEONAID_BACKUP_COMPOSE_OVERLAY="$source_overlay" \
  LEONAID_BACKUP_COMPOSE_OVERLAY_SECONDARY="$source_isolation" \
  /bin/sh "$root/tools/backup/backup.sh" "$root"

. "$root/tools/backup/survey-recovery-fixture.sh"
prepare_survey_recovery_fixture source_old "$proof"

LEONAID_COMPOSE_PROJECT="$source_project" \
  LEONAID_HTTP_PORT="$source_http_port" \
  LEONAID_HTTPS_PORT="$source_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_MAINTENANCE_COMPOSE_OVERLAY="$source_isolation" \
  /bin/sh "$root/infra/upgrade/maintenance.sh" enable "$root"
run_maintenance_contract source maintenance
running_writers=$(source_target ps --services --filter status=running)
for writer in worker twenty-server twenty-worker; do
  if echo "$running_writers" | grep -Fx "$writer" >/dev/null; then
    fail "Writer läuft im Wartungsmodus weiter: $writer"
  fi
done

# Releases before the non-root core image wrote the survey erasure archive as
# root. Turn the source archive into exactly that state; the upgrade must hand
# it to the core uid before api/worker write to it again.
archive_volume="${source_project}_survey-erasure-archive"
docker run --rm --network none --volume "$archive_volume:/archive" \
  "$ALPINE_IMAGE" sh -eu -c '
    : >/archive/.lock
    : >/archive/root-era-marker
    chown -R 0:0 /archive
    chmod 0700 /archive
    chmod 0600 /archive/.lock /archive/root-era-marker'

object_inventory source_old objects-before-upgrade
migrate_queue_store "$source_project"
source_target up --detach --force-recreate --wait --wait-timeout 420 \
  rustfs
verify_image "${source_project}-rustfs-1" "$RUSTFS_IMAGE"
object_inventory source_target objects-after-upgrade
require_same_objects objects-before-upgrade objects-after-upgrade
run_twenty_upgrade source primary
verify_valkey "$source_project"
verify_image "${source_project}-twenty-server-1" "$TWENTY_IMAGE"
LEONAID_COMPOSE_PROJECT="$source_project" \
  LEONAID_HTTP_PORT="$source_http_port" \
  LEONAID_HTTPS_PORT="$source_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_MAINTENANCE_COMPOSE_OVERLAY="$source_isolation" \
  /bin/sh "$root/infra/upgrade/maintenance.sh" disable "$root"
source_target --profile dev-mail up --detach --wait --wait-timeout 420
# The full release start recreates the data services on the target image.
verify_postgres "$source_project"
# Restart both writers like a release does: their startup publishes the
# erasure checkpoint into the handed-over archive.
source_target up --detach --force-recreate --no-deps --wait --wait-timeout 420 \
  core-volume-init api worker
archive_owners=$(docker run --rm --network none \
  --volume "$archive_volume:/archive:ro" "$ALPINE_IMAGE" \
  stat -c '%u:%g' /archive /archive/.lock /archive/root-era-marker | sort -u)
[ "$archive_owners" = "10001:10001" ] ||
  fail "root-era survey erasure archive was not handed to the core uid: $archive_owners"
for service in api worker; do
  source_target exec -T "$service" python -c 'import os
os.close(os.open("/recovery/survey-erasure/.lock", os.O_RDWR))' ||
    fail "$service cannot lock the upgraded survey erasure archive"
done
source_target exec -T api rm /recovery/survey-erasure/root-era-marker
echo "upgrade-test: root-era survey erasure archive handed to the core uid"
run_maintenance_contract source available
run_dashboard_contract source
snapshot_and_verify source post-upgrade golden
run_e2e "$source_project" after
run_full_golden_journey source "$source_project" after round-2
record_release_event \
  "$release_v2" staging_verified passed PILOT-043-STAGING-V2 \
  2026-07-28T08:40:00Z

# Retain source data but run only one full owned stack at a time.
source_target --profile '*' stop
restore_source_version
rollback_old build api public pwa web survey-validator proxy
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

rollback_target --profile '*' down --volumes --remove-orphans
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
object_inventory rollback_old objects-before-production
migrate_queue_store "$rollback_project"
rollback_target up --detach --force-recreate --wait --wait-timeout 420 \
  rustfs
verify_image "${rollback_project}-rustfs-1" "$RUSTFS_IMAGE"
object_inventory rollback_target objects-after-production
require_same_objects objects-before-production objects-after-production
run_twenty_upgrade rollback failure-clone
verify_valkey "$rollback_project"
LEONAID_COMPOSE_PROJECT="$rollback_project" \
  LEONAID_HTTP_PORT="$rollback_http_port" \
  LEONAID_HTTPS_PORT="$rollback_https_port" \
  TWENTY_INTEGRATION_API_KEY="$integration_key" \
  LEONAID_MAINTENANCE_COMPOSE_OVERLAY="$rollback_network_overlay" \
  /bin/sh "$root/infra/upgrade/maintenance.sh" disable "$root"
rollback_target --profile dev-mail up --detach --wait --wait-timeout 420
verify_postgres "$rollback_project"
run_dashboard_contract rollback
snapshot_and_verify rollback production-v2 golden
record_release_event \
  "$release_v2" production_verified passed PILOT-043-PRODUCTION-V2 \
  2026-07-28T09:40:00Z
rollback_target --profile dev-mail run --rm --user "$(id -u):$(id -g)" --no-deps \
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

rollback_target --profile '*' down --volumes --remove-orphans
record_release_event \
  "$release_v2" rollback_started passed PILOT-043-POST-SMOKE-ROLLBACK \
  2026-07-28T09:42:00Z
restore_source_version
rollback_old build api public pwa web survey-validator proxy
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
  "$proof"/objects-before-upgrade.json \
  "$proof"/objects-after-upgrade.json \
  "$proof"/objects-before-production.json \
  "$proof"/objects-after-production.json \
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
  --user "$(id -u):$(id -g)" \
  -v "$artifact_directory:/artifacts" \
  "$PYTHON_IMAGE" \
  python -c 'import json,pathlib
pathlib.Path("/artifacts/result.json").write_text(json.dumps({
  "schemaVersion":1,
  "result":"passed",
  "source":{"twenty":"2.24.0","rustfs":"1.0.0-beta.11","queueStore":"redis-7.4.12","postgres":"16.9"},
  "target":{"twenty":"2.54.0","rustfs":"1.0.4","queueStore":"valkey-9.1.3","postgres":"16.15"},
  "queueStoreMigration":"passed",
  "objectStoreUpgrade":"passed",
  "postgresMinorUpgrade":"passed",
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

echo "upgrade-test: OK: reale Twenty-, RustFS- und PostgreSQL-Upgrades,"
echo "upgrade-test:     Wartungsgrenze, Contract/E2E vor und nach dem Upgrade"
echo "upgrade-test:     vollständige Golden Journeys vor/nach Upgrade und Rollback"
echo "upgrade-test:     sowie Manifest-Promotion, Migrationsfehler und Recovery bewiesen"
