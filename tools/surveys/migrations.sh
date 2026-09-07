#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project="surveys-migrations-$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
proof=$(mktemp -d)
network=false
volume=false
container=false
cleanup() {
  status=$?
  if [ "$container" = true ]; then docker rm -f "$project" >/dev/null; fi
  if [ "$volume" = true ]; then docker volume rm "$project" >/dev/null; fi
  if [ "$network" = true ]; then docker network rm "$project" >/dev/null; fi
  docker image rm "$project" >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
docker build --file "$root/infra/compose/Dockerfile.core" --tag "$project" "$root"
subnet=$(python3 "$root/tools/surveys/network_override.py" --single)
docker network create --internal --subnet "$subnet" "$project" >/dev/null
network=true
docker volume create "$project" >/dev/null
volume=true
docker run --detach --name "$project" --network "$project" --network-alias postgres \
  --env POSTGRES_PASSWORD=synthetic-survey-proof \
  --volume "$project:/var/lib/postgresql/data" "$POSTGRES_IMAGE" >/dev/null
container=true
attempts=0
until docker exec "$project" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do
  attempts=$((attempts + 1))
  [ "$attempts" -lt 60 ] || { echo 'Migration database did not start' >&2; exit 1; }
  sleep 1
done
run() {
  database=$1
  entrypoint=$2
  shift 2
  docker run --rm --network "$project" \
    --env "CORE_DATABASE_URL=postgresql://postgres:synthetic-survey-proof@postgres:5432/$database" \
    --volume "$root:/repo:ro" --volume "$proof:/proof" --workdir /workspace \
    --entrypoint "$entrypoint" "$project" "$@"
}
docker exec "$project" createdb -U postgres survey_empty
run survey_empty alembic upgrade head
run survey_empty alembic upgrade head
run survey_empty python /repo/tools/surveys/migrations.py empty
docker exec "$project" createdb -U postgres survey_upgrade
run survey_upgrade alembic upgrade 0011_public_orders
docker exec -i "$project" psql -v ON_ERROR_STOP=1 -U postgres -d survey_upgrade < "$root/tests/fixtures/schema/v0.sql"
run survey_upgrade alembic upgrade 0026_invoice_payment_snapshot
run survey_upgrade python /repo/tools/surveys/migrations.py baseline
run survey_upgrade alembic upgrade head
run survey_upgrade alembic upgrade head
run survey_upgrade python /repo/tools/surveys/migrations.py upgrade
mkdir -p "$root/.artifacts/surveys-migrations"
cp "$proof"/*.json "$root/.artifacts/surveys-migrations/"
docker rm -f "$project" >/dev/null
container=false
docker volume rm "$project" >/dev/null
volume=false
docker network rm "$project" >/dev/null
network=false
echo "PASS: $project empty and existing-data upgrades, repeat migration, survey constraints and owned-resource teardown; no host ports"
