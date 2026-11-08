#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
seed_part=${LEONAID_SEED_PART:-all}
case "$seed_part" in all|reset) ;; *) exit 64 ;; esac
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
  echo "seed-test: ERROR: .env.local missing; run ./leonaid bootstrap first" >&2
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

# The data step of `./leonaid seed`; its provisioning and stack start are the
# same functions the final `./leonaid reset` runs cold.
golden_seed() {
  compose run --rm --user "$(id -u):$(id -g)" --no-deps \
    --env-from-file "$env_file" \
    --env-from-file "$root/.local/twenty/integration.env" \
    --volume "$root:/repo:ro" --entrypoint python api \
    /repo/tools/seed/golden.py seed /repo/tests/fixtures/golden/v1 \
    /repo/.artifacts/golden-v1/invoices
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "seed-test: diagnostics for the failed own services:" >&2
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
    if ! verify_owned_project_removed "$project"; then status=1; fi
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

echo "seed-test: proving a production DSN is refused before any deletion"
if compose config --format json |
  sed 's/@core-postgres:/@production-db.example.com:/' |
  docker run --rm -i \
    -v "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/seed/safety.py \
    --project-name "$project" \
    --env-file /workspace/.env.local; then
  echo "seed-test: ERROR: production DSN was not refused" >&2
  exit 1
fi

echo "seed-test: resetting all four systems from empty volumes to Golden Data v1"
if [ "$seed_part" = reset ]; then
  # Only the starting state is prepared. The reset after the real mutation below
  # still uses the unmodified operator CLI and creates new empty volumes.
  cp "$compose_file" "$proof/cold-compose.json"
  phase seed-fixture-import python3 "$checkout_root/tools/testing/seed_fixture.py" "$checkout_root" "$root" "$project"
  build_shared_images api
  phase seed-starting-services compose --profile dev-mail up --no-build --detach \
    --wait --wait-timeout 420 core-postgres rustfs mailpit twenty-server twenty-worker
  phase seed-starting-data golden_seed
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
  echo "seed-test: ERROR: local test logins are not protected by git ignore" >&2
  exit 1
fi
if compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --env-from-file "$env_file" \
  --env LEONAID_ENV=production \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/seed/golden.py \
  seed-core /repo/tests/fixtures/golden/v1; then
  echo "seed-test: ERROR: golden seeding was not refused in production" >&2
  exit 1
fi
"$root/leonaid" snapshot poc012-first.json
docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/seed/verify_snapshot.py golden \
  /repo/.local/snapshots/poc012-first.json \
  /repo/tests/fixtures/golden/v1

echo "seed-test: running a second idempotent seed"
# Per run the data step only; nightly (LEONAID_SEED_CLI=true, ci.yml) and in
# the local suite the whole operator command: re-provisioning, the api/worker
# recreate and its guards.
if [ "${LEONAID_SEED_CLI:-}" = true ] || [ "$seed_part" = all ]; then
  phase seed-second "$root/leonaid" seed
else
  phase seed-second golden_seed
fi
"$root/leonaid" snapshot poc012-second.json
docker run --rm \
  -v "$root/.local:/local:ro" \
  "$ALPINE_IMAGE" \
  cmp /local/snapshots/poc012-first.json /local/snapshots/poc012-second.json

echo "seed-test: changing PostgreSQL, Twenty, RustFS and Mailpit for real"
compose run --rm --user "$(id -u):$(id -g)" --no-deps \
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
  echo "seed-test: ERROR: intentional mutation did not change the snapshot" >&2
  exit 1
fi

echo "seed-test: reset restores the exact business snapshot"
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

echo "seed-test: OK: safety, idempotence, mutation and exact reset proven"
