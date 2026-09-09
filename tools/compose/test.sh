#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=${LEONAID_COMPOSE_TEST_PROJECT:-leonaid-poc010-test}-$suffix
owned=false
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
fixture="/repo/tests/fixtures/golden/v1"

if [ ! -f "$env_file" ]; then
  echo "compose-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap ausführen" >&2
  exit 1
fi

compose() {
  LEONAID_HTTP_PORT="$port" LEONAID_HTTPS_PORT="$https_port" docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    "$@"
}

compose_all_profiles() {
  compose --profile dev-mail --profile mailing --profile observability "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "compose-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=80 >&2 || true
  fi
  if [ "$owned" = true ]; then
    if ! compose_all_profiles down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
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

# Refuse collisions and inventory failures before any Docker mutation.
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$root/tools/surveys/network_override.py" "$isolation_file"
# This regression explicitly proves host bindings. Reserve two distinct free
# loopback ports while selecting them, then let Docker bind or fail closed.
python3 - "$proof/ports" "$isolation_file" "${LEONAID_COMPOSE_TEST_PORT:-0}" "${LEONAID_COMPOSE_TEST_HTTPS_PORT:-0}" <<'PYPORTS'
import socket
import sys
from contextlib import ExitStack
from pathlib import Path
with ExitStack() as stack:
    ports = []
    for requested in sys.argv[3:]:
        listener = stack.enter_context(socket.socket())
        listener.bind(("127.0.0.1", int(requested)))
        ports.append(listener.getsockname()[1])
    Path(sys.argv[1]).write_text(" ".join(map(str, ports)) + "\n")
    path = Path(sys.argv[2])
    path.write_text(path.read_text().replace(
        "    ports: !reset []",
        "    ports: !override\n"
        f'      - "127.0.0.1:{ports[0]}:8080"\n'
        f'      - "127.0.0.1:{ports[1]}:8443"',
    ))
PYPORTS
read -r port https_port < "$proof/ports"
owned=true

profiles=$(compose config --profiles | sort)
expected_profiles=$(printf '%s\n' \
  dev-mail mail-contract mailing observability storage-contract | sort)
if [ "$profiles" != "$expected_profiles" ]; then
  echo "compose-test: ERROR: unerwartete Profile: $profiles" >&2
  exit 1
fi

echo "compose-test: starte Standardstack aus leeren, projektspezifischen Volumes"
compose up --build --detach --wait --wait-timeout 420

expected_services=$(printf '%s\n' \
  api core-postgres proxy public pwa rustfs survey-validator twenty-postgres twenty-redis \
  twenty-server twenty-worker web worker | sort)
actual_services=$(compose ps --services --filter status=running | sort)
if [ "$actual_services" != "$expected_services" ]; then
  echo "compose-test: ERROR: Standarddienste weichen ab" >&2
  printf 'Erwartet:\n%s\nErhalten:\n%s\n' \
    "$expected_services" "$actual_services" >&2
  exit 1
fi

for service in $expected_services; do
  container_id=$(compose ps --quiet "$service")
  health=$(docker inspect --format '{{.State.Health.Status}}' "$container_id")
  if [ "$health" != "healthy" ]; then
    echo "compose-test: ERROR: $service ist $health" >&2
    exit 1
  fi
done

published_services=""
for service in $expected_services; do
  container_id=$(compose ps --quiet "$service")
  bindings=$(docker inspect --format \
    '{{range $port, $items := .NetworkSettings.Ports}}{{range $items}}{{println .HostIp .HostPort}}{{end}}{{end}}' \
    "$container_id")
  if [ -n "$bindings" ]; then
    prefixed_bindings=$(printf '%s\n' "$bindings" | sed "/^$/d; s/^/${service}:/")
    published_services="${published_services}${prefixed_bindings}
"
  fi
done
actual_bindings=$(printf '%s' "$published_services" | sed '/^$/d' | sort)
expected_bindings=$(printf '%s\n' \
  "proxy:127.0.0.1 $https_port" \
  "proxy:127.0.0.1 $port" | sort)
if [ "$actual_bindings" != "$expected_bindings" ]; then
  echo "compose-test: ERROR: nur der Proxy darf HTTP/HTTPS lokal veröffentlichen" >&2
  printf '%s' "$published_services" >&2
  exit 1
fi

base_url="http://127.0.0.1:$port"
test "$(curl --fail --silent "$base_url/_health")" = "ready"
test "$(curl --fail --insecure --silent "https://localhost:$https_port/_health")" = "ready"
curl --fail --silent "$base_url/api/health/ready" | grep -q '"status":"ready"'
curl --fail --silent "$base_url/app/" | grep -q "LeonAid Akquise"
curl --fail --silent "$base_url/admin/" | grep -q "Charity-Aktionen"
curl --fail --silent "$base_url/" | grep -q "Engagement, das ankommt"
curl --fail --silent \
  --resolve "crm.localhost:$port:127.0.0.1" \
  "http://crm.localhost:$port/healthz" | grep -q '"status":"ok"'

echo "compose-test: schreibe das echte Golden Dataset nach PostgreSQL und RustFS"
compose run --rm --no-deps \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/compose/persistence_probe.py write "$fixture"

twenty_tables_before=$(compose exec -T twenty-postgres sh -ec \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('"'"'pg_catalog'"'"', '"'"'information_schema'"'"');"')
if [ "$twenty_tables_before" -le 0 ]; then
  echo "compose-test: ERROR: Twenty-Schema wurde nicht aufgebaut" >&2
  exit 1
fi

echo "compose-test: startet alle Standardcontainer neu und wartet erneut auf Readiness"
compose restart
compose up --detach --wait --wait-timeout 420

compose run --rm --no-deps \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/compose/persistence_probe.py verify "$fixture"

twenty_tables_after=$(compose exec -T twenty-postgres sh -ec \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('"'"'pg_catalog'"'"', '"'"'information_schema'"'"');"')
if [ "$twenty_tables_after" != "$twenty_tables_before" ]; then
  echo "compose-test: ERROR: Twenty-Schema blieb beim Neustart nicht stabil" >&2
  exit 1
fi

echo "compose-test: startet und prüft optionale Profile"
if [ "${LEONAID_COMPOSE_PART:-all}" = base ]; then
  echo "compose-test: cold start, network boundaries and restart persistence passed"
  exit 0
fi
compose_all_profiles up --detach --wait --wait-timeout 420
for service in mailpit listmonk listmonk-postgres otel-collector; do
  container_id=$(compose ps --quiet "$service")
  health=$(docker inspect --format '{{.State.Health.Status}}' "$container_id")
  if [ "$health" != "healthy" ]; then
    echo "compose-test: ERROR: optionaler Dienst $service ist $health" >&2
    exit 1
  fi
done
curl --fail --silent "$base_url/mail/readyz" >/dev/null
curl --fail --silent "$base_url/mailing/health" >/dev/null

echo "compose-test: OK: leerer Start, Netzwerkgrenzen, Profile und Persistenz bewiesen"
