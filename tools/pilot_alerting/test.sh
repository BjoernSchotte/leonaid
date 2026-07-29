#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_PILOT_ALERTING_PROJECT:-leonaid-pilot042-test}
workspace=$(mktemp -d)
events_dir="$workspace/events"
events_file="$events_dir/events.jsonl"
manifest="$workspace/backup-manifest.json"
compose_file="$root/infra/compose/compose.yml"
alerting_compose="$root/infra/observability/pilot/compose.test.yml"
canary_email=monitoring-canary-person@example.invalid
canary_token=monitoring-canary-secret-token-042

mkdir -p "$events_dir"

compose() {
  LEONAID_HTTP_PORT=18142 \
    LEONAID_HTTPS_PORT=18442 \
    LEONAID_ALERT_TEST_PROJECT="$project" \
    LEONAID_ALERT_TEST_EVENTS_DIR="$events_dir" \
    LEONAID_ALERT_TEST_BACKUP_MANIFEST="$manifest" \
    docker compose \
      --project-name "$project" \
      --env-file "$root/.env.local" \
      --file "$compose_file" \
      --file "$alerting_compose" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "pilot-alerting-test: Diagnose:" >&2
    compose --profile dev-mail --profile monitoring ps --all >&2 || true
    compose --profile dev-mail --profile monitoring logs --no-color --tail=120 \
      api worker pilot-exporter prometheus alertmanager alert-sink >&2 || true
  fi
  compose --profile dev-mail --profile monitoring \
    down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$workspace"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

contract() {
  docker run --rm \
    --volume "$root:/workspace:ro" \
    --volume "$workspace:/proof" \
    --workdir /workspace \
    "$PYTHON_IMAGE" \
    python tools/pilot_alerting/contract.py "$@"
}

monitor_contract() {
  docker run --rm \
    --network "${project}_telemetry" \
    --volume "$root:/workspace:ro" \
    --workdir /workspace \
    "$PYTHON_IMAGE" \
    python tools/pilot_alerting/contract.py "$@"
}

wait_event() {
  alert=$1
  status=$2
  dependency=${3:-}
  if [ -n "$dependency" ]; then
    contract wait-event /proof/events/events.jsonl \
      --alert "$alert" --status "$status" --dependency "$dependency"
  else
    contract wait-event /proof/events/events.jsonl \
      --alert "$alert" --status "$status"
  fi
}

dependency_cycle() {
  service=$1
  dependency=$2
  echo "pilot-alerting-test: stoppt $service und erwartet Alarm/Recovery"
  compose stop "$service"
  wait_event LeonAidDependencyUnavailable firing "$dependency"
  compose start "$service"
  compose up --detach --wait --wait-timeout 180 "$service"
  wait_event LeonAidDependencyUnavailable resolved "$dependency"
}

if [ ! -f "$root/.env.local" ]; then
  echo "pilot-alerting-test: ERROR: .env.local fehlt" >&2
  exit 1
fi

contract write-manifest /proof/backup-manifest.json --project "$project"

docker run --rm --entrypoint /bin/promtool \
  --volume "$root/infra/observability/pilot:/etc/prometheus:ro" \
  "$PROMETHEUS_IMAGE" \
  check config /etc/prometheus/prometheus.yml
docker run --rm --entrypoint /bin/promtool \
  --volume "$root/infra/observability/pilot:/etc/prometheus:ro" \
  "$PROMETHEUS_IMAGE" \
  test rules /etc/prometheus/rules.test.yml
docker run --rm --entrypoint /bin/amtool \
  --volume "$root/infra/observability/pilot:/etc/alertmanager:ro" \
  --volume "$root/tests/fixtures/monitoring/alert-webhook-url:/run/secrets/alert-webhook-url:ro" \
  "$ALERTMANAGER_IMAGE" \
  check-config /etc/alertmanager/alertmanager.yml

compose --profile dev-mail --profile monitoring \
  down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api alert-sink pilot-exporter
compose --profile dev-mail --profile monitoring up --detach \
  --wait --wait-timeout 420 \
  core-postgres rustfs mailpit twenty-server twenty-worker api worker tls-probe

compose --profile monitoring up --detach --wait --wait-timeout 180 \
  alert-sink pilot-exporter alertmanager prometheus

docker run --rm --network "${project}_telemetry" "$ALPINE_IMAGE" \
  wget -qO- http://prometheus:9090/-/ready >/dev/null
docker run --rm --network "${project}_telemetry" "$ALPINE_IMAGE" \
  wget -qO- http://alertmanager:9093/-/ready >/dev/null
for check in backup disk tls; do
  monitor_contract assert-monitoring-status \
    --url http://pilot-exporter:8020/status \
    --check "$check" \
    --status ready
done

dependency_cycle twenty-server twenty
dependency_cycle rustfs rustfs
dependency_cycle mailpit mail
dependency_cycle worker worker

echo "pilot-alerting-test: erzeugt und heilt ein real veraltetes Backup"
contract write-manifest /proof/backup-manifest.json --project "$project" --stale
wait_event LeonAidBackupStale firing
monitor_contract assert-monitoring-status \
  --url http://pilot-exporter:8020/status \
  --check backup \
  --status critical
monitor_contract assert-alertmanager \
  --url http://alertmanager:9093/api/v2/alerts \
  --alert LeonAidBackupStale
contract write-manifest /proof/backup-manifest.json --project "$project"
wait_event LeonAidBackupStale resolved
monitor_contract assert-monitoring-status \
  --url http://pilot-exporter:8020/status \
  --check backup \
  --status ready

echo "pilot-alerting-test: füllt ein echtes 16-MiB-tmpfs bis unter 10 Prozent"
compose exec --no-TTY pilot-exporter \
  dd if=/dev/zero of=/run/leonaid-monitor/disk/capacity-test.bin \
  bs=1024 count=14800
wait_event LeonAidDiskLow firing
monitor_contract assert-monitoring-status \
  --url http://pilot-exporter:8020/status \
  --check disk \
  --status critical
monitor_contract assert-alertmanager \
  --url http://alertmanager:9093/api/v2/alerts \
  --alert LeonAidDiskLow
compose exec --no-TTY pilot-exporter \
  truncate --size 0 /run/leonaid-monitor/disk/capacity-test.bin
wait_event LeonAidDiskLow resolved
monitor_contract assert-monitoring-status \
  --url http://pilot-exporter:8020/status \
  --check disk \
  --status ready

echo "pilot-alerting-test: prüft synthetische PII gegen den Alarmkanal"
compose exec --no-TTY core-postgres sh -c \
  "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"
  INSERT INTO outbox_event (
    id, aggregate_type, aggregate_id, event_type, idempotency_key, payload,
    status, attempts, available_at, dead_lettered_at, last_error_code
  ) VALUES (
    '42000000-0000-4000-8000-000000000042',
    'pilot_canary',
    '42000000-0000-4000-8000-000000000042',
    'pilot.canary.v1',
    'pilot-alerting-canary-042',
    '{\\\"email\\\":\\\"$canary_email\\\",\\\"token\\\":\\\"$canary_token\\\"}'::jsonb,
    'dead_letter',
    1,
    now(),
    now(),
    'synthetic_canary'
  );\""
wait_event LeonAidDeadLetterPresent firing
contract assert-no-sensitive /proof/events/events.jsonl \
  "$canary_email" "$canary_token"
compose exec --no-TTY core-postgres sh -c \
  "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"
  DELETE FROM outbox_event
  WHERE id = '42000000-0000-4000-8000-000000000042';\""
wait_event LeonAidDeadLetterPresent resolved

if grep -E \
  'monitoring-canary-person|monitoring-canary-secret|\"payload\":\\{\"email\"' \
  "$events_file" >/dev/null 2>&1; then
  echo "pilot-alerting-test: ERROR: Alarmkanal enthält synthetische PII" >&2
  exit 1
fi

echo "pilot-alerting-test: OK: vier reale Ausfälle, Backup, Disk, Recovery,"
echo "pilot-alerting-test:     Wartungsgrenze und PII-freier Webhook bewiesen"
