#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_PILOT_IMPORT_TEST_PROJECT:-leonaid-pilot030-test}
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
proof=$(mktemp -d)
workspace="$proof/workspace"
container_workspace=/proof/workspace
host_user_id=$(id -u)
host_group_id=$(id -g)

[ -f "$env_file" ] || {
  echo "pilot-import-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap ausführen" >&2
  exit 1
}

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    "$@"
}

diagnose() {
  compose ps >&2 || true
  compose logs --no-color --tail=100 twenty-server twenty-worker api >&2 || true
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    diagnose
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

run_python() {
  compose run --rm --no-deps \
    --user "$host_user_id:$host_group_id" \
    --env-from-file "$env_file" \
    --env-from-file "$proof/integration.env" \
    --env PYTHONPATH=/repo/src:/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api "$@"
}

protocol() {
  command=$1
  shift
  run_python tools/pilot_import/protocol.py "$command" \
    "$container_workspace/.local/pilot/intake/historic-contacts.xlsx" \
    --root "$container_workspace" \
    --batch-id IMPORT-GOLDEN-001 \
    --target-environment staging-golden \
    --manifest "$container_workspace/.local/pilot/manifests/intake.json" \
    --mapping "$container_workspace/infra/twenty/import-mapping.json" \
    --sheet Kontakte \
    --report "$container_workspace/.local/pilot/evidence/$command.json" \
    "$@"
}

provision() {
  compose run --rm --no-deps \
    --user "$host_user_id:$host_group_id" \
    --env-from-file "$env_file" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api tools/twenty/provision.py apply \
    --token-output /proof/integration.env \
    --snapshot-output /proof/schema.json
}

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose build api
compose up --detach --wait --wait-timeout 420 \
  core-postgres twenty-redis rustfs api twenty-server twenty-worker
provision
run_python tools/seed/golden.py seed-twenty /repo/tests/fixtures/golden/v1
run_python tools/pilot_import/test.py prepare /repo "$container_workspace"
run_python tools/pilot_import/test.py check-damaged "$container_workspace"

backup="$workspace/.local/pilot/backups"
compose exec -T core-postgres pg_dump \
  --username leonaid \
  --dbname leonaid \
  --format custom \
  --no-owner \
  --no-privileges >"$backup/core.dump"
compose exec -T twenty-postgres pg_dump \
  --username twenty \
  --dbname default \
  --format custom \
  --no-owner \
  --no-privileges >"$backup/twenty.dump"
docker run --rm \
  --volume "${project}_twenty-server-data:/source:ro" \
  --volume "$backup:/backup" \
  "$ALPINE_IMAGE" \
  tar -C /source -cf /backup/twenty-storage.tar .
docker run --rm \
  --volume "${project}_rustfs-data:/source:ro" \
  --volume "$backup:/backup" \
  "$ALPINE_IMAGE" \
  tar -C /source -cf /backup/rustfs-data.tar .
run_python tools/pilot_import/test.py \
  write-backup-manifest "$container_workspace" leonaid-staging-golden

echo "pilot-import-test: ungeklärter Konflikt bleibt sichtbar"
protocol dry-run \
  --report "$container_workspace/.local/pilot/evidence/unresolved.json"
run_python tools/pilot_import/test.py resolve "$container_workspace"

echo "pilot-import-test: zwei identische Dry Runs sind bytegleich"
protocol dry-run \
  --resolutions "$container_workspace/.local/pilot/manifests/resolutions.json" \
  --report "$container_workspace/.local/pilot/evidence/dry-a.json" \
  --summary "$container_workspace/.local/pilot/evidence/summary.json"
protocol dry-run \
  --resolutions "$container_workspace/.local/pilot/manifests/resolutions.json" \
  --report "$container_workspace/.local/pilot/evidence/dry-b.json"
run_python tools/pilot_import/test.py approve "$container_workspace"
run_python tools/pilot_import/test.py \
  write-negative-manifests "$container_workspace"

echo "pilot-import-test: ungeklärter Konflikt blockiert Apply vor dem ersten Write"
if protocol apply \
  --approval "$container_workspace/.local/pilot/manifests/approval.json" \
  --backup-manifest "$container_workspace/.local/pilot/backups/manifest.json" \
  --report "$container_workspace/.local/pilot/evidence/unresolved-apply.json"; then
  echo "pilot-import-test: ERROR: ungeklärter Konflikt wurde angewendet" >&2
  exit 1
fi

echo "pilot-import-test: paralleles Apply desselben Batches wird gesperrt"
ready="$proof/lock-ready"
release="$proof/lock-release"
run_python tools/pilot_import/test.py hold-lock \
  "$container_workspace" /proof/lock-ready /proof/lock-release &
lock_pid=$!
attempts=0
while [ ! -f "$ready" ]; do
  attempts=$((attempts + 1))
  [ "$attempts" -lt 200 ] || {
    echo "pilot-import-test: ERROR: Lock-Prozess wurde nicht bereit" >&2
    exit 1
  }
  sleep 0.05
done
if protocol apply \
  --resolutions "$container_workspace/.local/pilot/manifests/resolutions.json" \
  --approval "$container_workspace/.local/pilot/manifests/approval.json" \
  --backup-manifest "$container_workspace/.local/pilot/backups/manifest.json" \
  --report "$container_workspace/.local/pilot/evidence/concurrent.json"; then
  echo "pilot-import-test: ERROR: konkurrierendes Apply wurde nicht gesperrt" >&2
  exit 1
fi
touch "$release"
wait "$lock_pid"

echo "pilot-import-test: manipulierter Fingerprint wird fail-closed abgewiesen"
cp "$workspace/infra/twenty/import-mapping.json" "$proof/mapping.original.json"
printf '\n' >>"$workspace/infra/twenty/import-mapping.json"
if protocol apply \
  --resolutions "$container_workspace/.local/pilot/manifests/resolutions.json" \
  --approval "$container_workspace/.local/pilot/manifests/approval.json" \
  --backup-manifest "$container_workspace/.local/pilot/backups/manifest.json" \
  --report "$container_workspace/.local/pilot/evidence/tampered.json"; then
  echo "pilot-import-test: ERROR: manipulierter Fingerprint wurde akzeptiert" >&2
  exit 1
fi
mv "$proof/mapping.original.json" "$workspace/infra/twenty/import-mapping.json"

echo "pilot-import-test: stale Resolution wird fail-closed abgewiesen"
if protocol apply \
  --resolutions "$container_workspace/.local/pilot/manifests/stale-resolutions.json" \
  --approval "$container_workspace/.local/pilot/manifests/approval.json" \
  --backup-manifest "$container_workspace/.local/pilot/backups/manifest.json" \
  --report "$container_workspace/.local/pilot/evidence/stale-resolution.json"; then
  echo "pilot-import-test: ERROR: stale Resolution wurde akzeptiert" >&2
  exit 1
fi

echo "pilot-import-test: Recovery Point einer anderen Umgebung wird abgewiesen"
if protocol apply \
  --resolutions "$container_workspace/.local/pilot/manifests/resolutions.json" \
  --approval "$container_workspace/.local/pilot/manifests/approval.json" \
  --backup-manifest "$container_workspace/.local/pilot/backups/wrong-target-manifest.json" \
  --report "$container_workspace/.local/pilot/evidence/wrong-recovery.json"; then
  echo "pilot-import-test: ERROR: falscher Recovery Point wurde akzeptiert" >&2
  exit 1
fi

echo "pilot-import-test: freigegebener Apply schreibt exakt den Dry Run"
protocol apply \
  --resolutions "$container_workspace/.local/pilot/manifests/resolutions.json" \
  --approval "$container_workspace/.local/pilot/manifests/approval.json" \
  --backup-manifest "$container_workspace/.local/pilot/backups/manifest.json" \
  --report "$container_workspace/.local/pilot/evidence/apply.json"
protocol verify \
  --resolutions "$container_workspace/.local/pilot/manifests/resolutions.json" \
  --backup-manifest "$container_workspace/.local/pilot/backups/manifest.json" \
  --report "$container_workspace/.local/pilot/evidence/verify.json"

echo "pilot-import-test: realer Recovery Point stellt den Vorzustand wieder her"
compose stop twenty-worker twenty-server api >/dev/null
compose exec -T twenty-postgres pg_restore \
  --username twenty \
  --dbname default \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges <"$backup/twenty.dump"
compose exec -T core-postgres pg_restore \
  --username leonaid \
  --dbname leonaid \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges <"$backup/core.dump"
compose start api twenty-server twenty-worker >/dev/null
compose up --detach --wait --wait-timeout 420 api twenty-server twenty-worker
protocol dry-run \
  --report "$container_workspace/.local/pilot/evidence/restored.json"

run_python tools/pilot_import/test.py check-reports "$container_workspace"

echo "pilot-import-test: OK: privater Intake, echte XLSX, realer Twenty/Core/RustFS-Recovery-Point, Fingerprint, Vier-Augen-Freigabe, Konflikte, Concurrency, Apply, Verify und Restore bewiesen"
