#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
seed_part=${LEONAID_SEED_PART:-all}
case "$seed_part" in all|cold|reset) ;; *) exit 64 ;; esac
. "$root/infra/locks/images.env"
. "$root/tools/testing/phase.sh"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc012-test-$suffix
owned=false
checkout_root="$root"
mkdir -p "$root/.artifacts"
proof=$(mktemp -d "$root/.artifacts/seed-regression.XXXXXX")
chmod 700 "$proof"
isolation_file="$proof/isolation.yml"
port=18082
https_port=18445
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
fixture="$root/tests/fixtures/golden/v1"
snapshot_directory="$root/.local/snapshots"

if [ ! -f "$env_file" ]; then
  echo "seed-test: ERROR: .env.local fehlt; zuerst ./leonaid bootstrap ausführen" >&2
  exit 1
fi

export LEONAID_COMPOSE_PROJECT="$project"
export LEONAID_HTTP_PORT="$port"
export LEONAID_HTTPS_PORT="$https_port"

compose() {
  if [ -n "$isolation_file" ]; then set -- --file "$isolation_file" "$@"; fi
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --profile dev-mail \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "seed-test: Diagnose der fehlgeschlagenen eigenen Services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=100 >&2 || true
  fi
  if [ "$owned" = true ]; then
    if ! compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    # The harness owns these externally declared networks across both CLI resets.
    networks=$(docker network ls -q --filter "label=com.docker.compose.project=$project") || status=1
    for network in $networks; do
      if ! docker network rm "$network" >/dev/null; then status=1; fi
    done
    for inventory in containers volumes networks; do
      case "$inventory" in
        containers) remaining=$(docker ps -aq --filter "label=com.docker.compose.project=$project") || status=1 ;;
        volumes) remaining=$(docker volume ls -q --filter "label=com.docker.compose.project=$project") || status=1 ;;
        networks) remaining=$(docker network ls -q --filter "label=com.docker.compose.project=$project") || status=1 ;;
      esac
      if [ -n "$remaining" ]; then status=1; fi
    done
    if [ "$status" -eq 0 ]; then echo "test-isolation: $project passed and owned resources were removed"; fi
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

# Refuse occupied or unreadable resource identities before cloning or mutation.
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$checkout_root/tools/seed/safety_test.py"
# Run the real operator CLI with its own .local, generated artifacts and Git ignore rules.
# Only the reset-name safety change may differ from the recorded source checkpoint.
python3 - "$checkout_root" "$proof/checkout" <<'PY_CHECKOUT'
from pathlib import Path
import shutil
import subprocess
import sys
source, target = map(Path, sys.argv[1:])
target.mkdir(mode=0o700)
commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
archive = subprocess.Popen(["git", "-C", str(source), "archive", commit], stdout=subprocess.PIPE)
try:
    subprocess.run(["tar", "-xf", "-", "-C", str(target)], stdin=archive.stdout, check=True)
finally:
    archive.stdout.close()
assert archive.wait() == 0
subprocess.run(["git", "-C", str(target), "init", "--quiet"], check=True)
shutil.copy2(source / ".env.local", target / ".env.local")
(target / ".env.local").chmod(0o600)
shutil.copy2(source / "tools/seed/safety.py", target / "tools/seed/safety.py")
print(f"seed-test: isolated operator source checkpoint {commit}")
PY_CHECKOUT
root="$proof/checkout"
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
fixture="$root/tests/fixtures/golden/v1"
snapshot_directory="$root/.local/snapshots"
python3 "$checkout_root/tools/surveys/network_override.py" "$isolation_file"
owned=true
compose --profile '*' config --format json | python3 "$checkout_root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
# Preserve environment interpolation so the real CLI can install its newly provisioned key.
compose --profile '*' config --no-interpolate --format json >"$proof/operator-compose.json"
python3 - "$proof/operator-compose.json" "$compose_file" "$project" <<'PY_NETWORKS'
import json
from pathlib import Path
import sys
config = json.loads(Path(sys.argv[1]).read_text())
project = sys.argv[3]
for key, network in config["networks"].items():
    assert network["name"] == f"{project}_{key}"
    config["networks"][key] = {"name": network["name"], "external": True}
path = Path(sys.argv[2])
path.write_text(json.dumps(config, indent=2) + "\n")
path.chmod(0o600)
PY_NETWORKS
isolation_file=""

echo "seed-test: beweist Ablehnung eines Produktions-DSN vor jeder Löschung"
if compose config --format json |
  sed 's/@core-postgres:/@production-db.example.com:/' |
  docker run --rm -i \
    -v "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/seed/safety.py \
    --project-name "$project" \
    --env-file /workspace/.env.local; then
  echo "seed-test: ERROR: Produktions-DSN wurde nicht abgewiesen" >&2
  exit 1
fi

echo "seed-test: setzt alle vier Systeme aus leeren Volumes auf Golden Data v1"
if [ "$seed_part" = reset ]; then
  # Only the starting state is prepared. The reset after the real mutation below
  # still uses the unmodified operator CLI and creates new empty volumes.
  cp "$compose_file" "$proof/cold-compose.json"
  phase seed-fixture-import python3 "$checkout_root/tools/testing/seed_fixture.py" "$checkout_root" "$root" "$project"
  compose build api
  phase seed-starting-services compose --profile dev-mail up --no-build --detach \
    --wait --wait-timeout 420 core-postgres rustfs mailpit twenty-server twenty-worker
  phase seed-starting-data compose run --rm --no-deps \
    --env-from-file "$env_file" \
    --env-from-file "$root/.local/twenty/integration.env" \
    --volume "$root:/repo:ro" --entrypoint python api \
    /repo/tools/seed/golden.py seed /repo/tests/fixtures/golden/v1 \
    /repo/.artifacts/golden-v1/invoices
  docker run --rm --user "$(id -u):$(id -g)" \
    --env LEONAID_ENV=local -v "$root:/workspace" "$PYTHON_IMAGE" \
    python /workspace/tools/dx/generate_test_logins.py \
    /workspace/tests/fixtures/golden/v1/dataset.json /workspace/.local/test-logins.md
  cp "$proof/cold-compose.json" "$compose_file"
else
  "$root/leonaid" reset
fi
docker run --rm \
  --env LEONAID_ENV=local \
  -v "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/dx/generate_test_logins.py \
  /workspace/tests/fixtures/golden/v1/dataset.json \
  /workspace/.local/test-logins.md \
  --check
if ! git -C "$root" check-ignore -q .local/test-logins.md; then
  echo "seed-test: ERROR: lokale Testlogins sind nicht durch Git-Ignore geschützt" >&2
  exit 1
fi
if compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env LEONAID_ENV=production \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py \
  seed-core /repo/tests/fixtures/golden/v1; then
  echo "seed-test: ERROR: Golden-Seeding wurde in Produktion nicht abgewiesen" >&2
  exit 1
fi
"$root/leonaid" snapshot poc012-first.json
docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/seed/verify_snapshot.py golden \
  /repo/.local/snapshots/poc012-first.json \
  /repo/tests/fixtures/golden/v1

echo "seed-test: führt einen zweiten idempotenten Seed aus"
if [ "$seed_part" != reset ]; then
"$root/leonaid" seed
"$root/leonaid" snapshot poc012-second.json
docker run --rm \
  -v "$root/.local:/local:ro" \
  "$ALPINE_IMAGE" \
  cmp /local/snapshots/poc012-first.json /local/snapshots/poc012-second.json
fi
if [ "$seed_part" = cold ]; then
  echo "seed-test: cold installation and idempotent seed passed"
  exit 0
fi

echo "seed-test: verändert PostgreSQL, Twenty, RustFS und Mailpit real"
compose run --rm --no-deps \
  --env-from-file "$env_file" \
  --env MAIL_SMTP_HOST=mailpit \
  --env MAIL_SMTP_PORT=1025 \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py mutate /repo/tests/fixtures/golden/v1
"$root/leonaid" snapshot poc012-mutated.json
docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/seed/verify_snapshot.py mutated \
  /repo/.local/snapshots/poc012-mutated.json \
  /repo/tests/fixtures/golden/v1
if docker run --rm \
  -v "$root/.local:/local:ro" \
  "$ALPINE_IMAGE" \
  cmp -s /local/snapshots/poc012-first.json /local/snapshots/poc012-mutated.json; then
  echo "seed-test: ERROR: absichtliche Mutation änderte den Snapshot nicht" >&2
  exit 1
fi

echo "seed-test: Reset stellt den exakten fachlichen Snapshot wieder her"
"$root/leonaid" reset
"$root/leonaid" snapshot poc012-restored.json
docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/seed/verify_snapshot.py golden \
  /repo/.local/snapshots/poc012-restored.json \
  /repo/tests/fixtures/golden/v1
docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/seed/verify_snapshot.py equivalent \
  /repo/.local/snapshots/poc012-first.json \
  /repo/.local/snapshots/poc012-restored.json

echo "seed-test: OK: Sicherheit, Idempotenz, Mutation und exakter Reset bewiesen"
