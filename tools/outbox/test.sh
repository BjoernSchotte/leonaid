#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(CDPATH= cd -- "$root" && pwd)
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
  compose run --rm --no-deps \
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
    for inventory in containers volumes networks; do
      case "$inventory" in
        containers) remaining=$(docker ps -aq --filter "label=com.docker.compose.project=$project") || status=1 ;;
        volumes) remaining=$(docker volume ls -q --filter "label=com.docker.compose.project=$project") || status=1 ;;
        networks) remaining=$(docker network ls -q --filter "label=com.docker.compose.project=$project") || status=1 ;;
      esac
      if [ -n "$remaining" ]; then
        echo "test-isolation: owned $inventory remain for $project" >&2
        status=1
      fi
    done
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
compose build api worker
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
