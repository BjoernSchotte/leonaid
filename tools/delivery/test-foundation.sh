#!/bin/sh
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"
database=""
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$database" ]; then docker rm -f "$database" >/dev/null || status=1; fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
# A private network namespace: no host ports, named network or persistent volume.
# The runner shares only this run's database loopback interface.
database=$(docker run -d --network none --tmpfs /var/lib/postgresql/data \
  --label leonaid.proof=krapfentaxi-delivery \
  -e POSTGRES_PASSWORD=isolated-delivery-proof -e POSTGRES_DB=delivery_proof \
  "$POSTGRES_IMAGE")
attempt=0
until docker exec "$database" pg_isready -U postgres >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then exit 1; fi
  sleep 1
done
docker run --rm --network "container:$database" \
  -v "$root:/workspace:ro" -w /workspace \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONUNBUFFERED=1 -e PYTHONPATH=/workspace/src:/workspace \
  -e CORE_DATABASE_URL=postgresql://postgres:isolated-delivery-proof@127.0.0.1/delivery_proof \
  "$UV_IMAGE" /workspace/.venv/bin/python tools/delivery/foundation.py
