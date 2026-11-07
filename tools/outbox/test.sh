#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(CDPATH= cd -- "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc022-test-$suffix
owned=false
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
mail_event_id=f3000000-0000-4000-8000-000000000001

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    --profile dev-mail \
    "$@"
}

api_probe() {
  compose run --rm --user "$(id -u):$(id -g)" --no-deps \
    --env MAIL_SMTP_HOST=mailpit \
    --env MAIL_SMTP_PORT=1025 \
    --volume "$root:/repo:ro" \
    api python /repo/tools/outbox/probe.py "$@"
}

outbox_cli() {
  compose run --rm --no-deps \
    worker python -m leonaid.entrypoints.worker.outbox "$@"
}

cleanup() {
  status=$?
  if [ "$owned" = true ]; then
    if ! compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    if ! verify_owned_project_removed "$project"; then status=1; fi
    if [ "$status" -eq 0 ]; then echo "test-isolation: $project passed and owned resources were removed"; fi
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

# Refuse existing resources and unreadable inventories before Docker mutations.
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$root/tools/surveys/network_override.py" "$isolation_file"
owned=true
compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
build_shared_images api worker
compose up --detach --wait --wait-timeout 120 core-postgres mailpit
compose run --rm --no-deps api alembic upgrade head
api_probe prepare

echo "poc022-test: stops the producer after commit and before dispatch"
if api_probe produce-crash; then
  echo "poc022-test: ERROR: crash probe ended successfully, which was not expected" >&2
  exit 1
fi
api_probe verify-crash
outbox_cli \
  --worker-id poc022-recovery-worker \
  --base-backoff-seconds 0 \
  run-until-idle
api_probe verify-recovery

echo "poc022-test: starts two real worker processes against the same queue"
api_probe produce-many --count 20
outbox_cli \
  --worker-id poc022-worker-a \
  --base-backoff-seconds 0 \
  run-until-idle --maximum-events 10 &
worker_a_pid=$!
outbox_cli \
  --worker-id poc022-worker-b \
  --base-backoff-seconds 0 \
  run-until-idle --maximum-events 10 &
worker_b_pid=$!
wait "$worker_a_pid"
wait "$worker_b_pid"
api_probe verify-concurrency --count 20

echo "poc022-test: forces SMTP retries and dead letter through a real outage"
compose stop mailpit
api_probe enqueue-mail
outbox_cli \
  --worker-id poc022-failing-worker \
  --max-attempts 3 \
  --base-backoff-seconds 0 \
  run-until-idle
api_probe verify-dead-letter
outbox_cli status "$mail_event_id"

compose up --detach --wait --wait-timeout 60 mailpit
outbox_cli retry "$mail_event_id" --operator poc022-operator
outbox_cli \
  --worker-id poc022-recovery-worker \
  --max-attempts 3 \
  --base-backoff-seconds 0 \
  run-until-idle
api_probe replay-and-verify-mail

echo "poc022-test: a worker whose lease expired must not overwrite the new claim"
api_probe verify-claim-loss
api_probe handler-timeout
api_probe parked-jobs

echo "poc022-test: retention deletes only expired completed jobs, in bounded batches"
api_probe verify-retention
api_probe seed-retention-cli
retention_output=$(outbox_cli retention-sweep)
printf '%s\n' "$retention_output"
case "$retention_output" in
  *'"outbox_events_deleted":2,'*'"complete":true'*) ;;
  *)
    echo "poc022-test: ERROR: unexpected retention-sweep result" >&2
    exit 1
    ;;
esac
api_probe verify-retention-cli

echo "poc022-test: OK: UoW, crash recovery, worker fencing, retry, dead letter, idempotency, retention, handler timeout and parked jobs proven"
