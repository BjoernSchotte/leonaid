#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(CDPATH= cd -- "$root" && pwd)
project=leonaid-poc022-test
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
mail_event_id=f3000000-0000-4000-8000-000000000001

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --profile dev-mail \
    "$@"
}

api_probe() {
  compose run --rm --no-deps \
    --volume "$root:/repo:ro" \
    api python /repo/tools/outbox/probe.py "$@"
}

outbox_cli() {
  compose run --rm --no-deps \
    api python -m leonaid.entrypoints.worker.outbox "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

cleanup
compose build api
compose up --detach --wait --wait-timeout 120 core-postgres mailpit
compose run --rm --no-deps api alembic upgrade head
api_probe prepare

echo "poc022-test: beendet den Producer nach Commit und vor Dispatch"
if api_probe produce-crash; then
  echo "poc022-test: ERROR: Crash-Probe endete unerwartet erfolgreich" >&2
  exit 1
fi
api_probe verify-crash
outbox_cli \
  --worker-id poc022-recovery-worker \
  --base-backoff-seconds 0 \
  run-until-idle
api_probe verify-recovery

echo "poc022-test: startet zwei reale Worker-Prozesse gegen dieselbe Queue"
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

echo "poc022-test: erzwingt SMTP-Retries und Dead Letter durch echten Ausfall"
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

echo "poc022-test: OK: UoW, Crash-Recovery, Worker-Fencing, Retry, Dead Letter und Idempotenz bewiesen"
