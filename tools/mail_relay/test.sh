#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_MAIL_RELAY_TEST_PROJECT:-leonaid-pilot020-test}-$suffix
owned=false
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "mail-relay-test: Diagnose der fehlgeschlagenen Services:" >&2
    compose --profile dev-mail --profile mail-contract ps --all >&2 || true
    compose --profile dev-mail --profile mail-contract logs \
      --no-color --tail=200 \
      mailpit mailpit-contract-starttls mailpit-contract-tls \
      mailpit-contract-chaos \
      mail-contract-blackhole >&2 || true
  fi
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

if [ ! -f "$env_file" ]; then
  echo "mail-relay-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap" >&2
  exit 1
fi

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
compose build api
compose --profile dev-mail --profile mail-contract up \
  --detach --wait --wait-timeout 120 \
  mailpit mailpit-contract-starttls mailpit-contract-tls \
  mailpit-contract-chaos \
  mail-contract-blackhole

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env PYTHONPATH=/repo:/workspace/src \
  --env MAIL_CONTRACT_PLAIN_HOST=mailpit \
  --env MAIL_CONTRACT_PLAIN_API=http://mailpit:8025/mail \
  --env MAIL_CONTRACT_STARTTLS_HOST=mailpit-contract-starttls \
  --env MAIL_CONTRACT_STARTTLS_API=http://mailpit-contract-starttls:8025 \
  --env MAIL_CONTRACT_TLS_HOST=mailpit-contract-tls \
  --env MAIL_CONTRACT_TLS_API=http://mailpit-contract-tls:8025 \
  --env MAIL_CONTRACT_CHAOS_HOST=mailpit-contract-chaos \
  --env MAIL_CONTRACT_BLACKHOLE_HOST=mail-contract-blackhole \
  --volume "$root:/repo:ro" \
  --volume "$proof:/proof" \
  --workdir /repo \
  --entrypoint python \
  api tools/mail_relay/contract.py

echo "mail-relay-test: OK: Plain-SMTP, STARTTLS/TLS/Auth, Zertifikat,"
echo "mail-relay-test:     Provider-Limit, Timeout und exakt-einmal Retry bewiesen"
