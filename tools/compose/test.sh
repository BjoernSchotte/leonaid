#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
project=${LEONAID_COMPOSE_TEST_PROJECT:-leonaid-poc010-test}
port=${LEONAID_COMPOSE_TEST_PORT:-18080}
https_port=${LEONAID_COMPOSE_TEST_HTTPS_PORT:-18443}
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
    "$@"
}

compose_all_profiles() {
  compose --profile dev-mail --profile mailing --profile observability "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "compose-test: Diagnose der fehlgeschlagenen echten Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=80 >&2 || true
  fi
  compose_all_profiles down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

compose_all_profiles down --volumes --remove-orphans >/dev/null 2>&1 || true

profiles=$(compose config --profiles | sort)
expected_profiles=$(printf '%s\n' dev-mail mailing observability | sort)
if [ "$profiles" != "$expected_profiles" ]; then
  echo "compose-test: ERROR: unerwartete Profile: $profiles" >&2
  exit 1
fi

echo "compose-test: starte Standardstack aus leeren, projektspezifischen Volumes"
compose up --build --detach --wait --wait-timeout 420

expected_services=$(printf '%s\n' \
  api core-postgres proxy public pwa rustfs twenty-postgres twenty-redis \
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
curl --fail --silent "$base_url/admin/" | grep -q "LeonAid Verwaltung"
curl --fail --silent "$base_url/" | grep -q "Krapfentaxi 2026"
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
