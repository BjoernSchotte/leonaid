#!/bin/sh
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"
scratch=$(mktemp -d)
network=""
database=""
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$database" ]; then docker rm -f "$database" >/dev/null; fi
  if [ -n "$network" ]; then docker network rm "$network" >/dev/null; fi
  rmdir "$scratch"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
# Docker assigns immutable IDs. Cleanup uses only resources created by this run.
# No shared Compose project, host port, persistent volume or existing container.
network=$(docker network create --internal --label leonaid.proof=delivery-foundation \
  "leonaid-delivery-$(basename "$scratch" | tr '[:upper:]' '[:lower:]')")
database=$(docker run -d --network "$network" --network-alias delivery-db \
  --label leonaid.proof=delivery-foundation \
  --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=isolated-delivery-proof -e POSTGRES_DB=delivery_proof \
  "$POSTGRES_IMAGE")
attempt=0
until docker exec "$database" pg_isready -U postgres >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then exit 1; fi
  sleep 1
done
docker run --rm --network "$network" \
  -v "$root:/workspace:ro" -w /workspace \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/workspace/src \
  -e CORE_DATABASE_URL=postgresql://postgres:isolated-delivery-proof@delivery-db/delivery_proof \
  "$UV_IMAGE" /workspace/.venv/bin/python tools/delivery/foundation.py
