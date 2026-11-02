#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"

suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc030-test-$suffix
owned=false
port=18083
env_file="$root/.env.local"
compose_file="$root/infra/compose/compose.yml"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
host_user_id=$(id -u)
host_group_id=$(id -g)

if [ ! -f "$env_file" ]; then
  echo "twenty-test: ERROR: .env.local missing; run ./leonaid bootstrap first" >&2
  exit 1
fi

export LEONAID_HTTP_PORT="$port"

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    "$@"
}

diagnose() {
  compose ps >&2 || true
  compose logs --no-color --tail=120 twenty-server twenty-worker >&2 || true
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "twenty-test: diagnostics for the failed real services:" >&2
    diagnose
  fi
  if [ "$owned" = true ]; then
    if ! compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    if ! verify_owned_project_removed "$project"; then status=1; fi
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

run_tool() {
  compose run --rm --no-deps \
    --user "$host_user_id:$host_group_id" \
    --env-from-file "$env_file" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --volume "$proof:/proof" \
    --workdir /repo \
    --entrypoint python \
    api tools/twenty/provision.py "$@"
}

compose build api
compose up --detach --wait --wait-timeout 420 twenty-server twenty-worker

echo "twenty-test: provisions an empty Twenty instance via the Metadata API"
run_tool apply \
  --token-output /proof/integration.env \
  --snapshot-output /proof/first.json

echo "twenty-test: repeats provisioning without duplicates or drift"
run_tool apply \
  --token-output /proof/integration.env \
  --snapshot-output /proof/second.json
docker run --rm \
  --volume "$proof:/proof:ro" \
  "$ALPINE_IMAGE" \
  cmp /proof/first.json /proof/second.json

echo "twenty-test: drops the workspace cache on purpose; Twenty rebuilds it"
# The stale-cache repair of provision.py deletes exactly Twenty's
# engine:workspace namespace; queues and other namespaces stay untouched.
workspace_keys() {
  compose exec -T twenty-redis redis-cli --scan --pattern 'engine:workspace:*' | wc -l
}
[ "$(workspace_keys)" -gt 0 ]
compose exec -T twenty-redis redis-cli SET engine:lock:leonaid-cache-probe kept >/dev/null
queue_keys_before=$(compose exec -T twenty-redis redis-cli --scan --pattern 'bull:*' | wc -l)
run_tool flush-workspace-cache
[ "$(workspace_keys)" -eq 0 ]
[ "$(compose exec -T twenty-redis redis-cli GET engine:lock:leonaid-cache-probe)" = kept ]
[ "$(compose exec -T twenty-redis redis-cli --scan --pattern 'bull:*' | wc -l)" -ge "$queue_keys_before" ]
compose exec -T twenty-redis redis-cli DEL engine:lock:leonaid-cache-probe >/dev/null
run_tool check --snapshot-output /proof/after-cache-flush.json
docker run --rm \
  --volume "$proof:/proof:ro" \
  "$ALPINE_IMAGE" \
  cmp /proof/first.json /proof/after-cache-flush.json
[ "$(workspace_keys)" -gt 0 ]

echo "twenty-test: proves allowed and denied integration key permissions"
run_tool verify-key --token-file /proof/integration.env

echo "twenty-test: changes a real field and expects a clear drift report"
run_tool mutate-field \
  --object charityAction \
  --field goalValue \
  --label "ABSICHTLICHER POC-030 DRIFT"
run_tool mutate-field \
  --object company \
  --field leonaidMatchKey \
  --label "ABSICHTLICHER MATCH-KEY DRIFT"
if run_tool check >"$proof/drift.log" 2>&1; then
  echo "twenty-test: ERROR: intentional field drift was not detected" >&2
  exit 1
fi
if ! grep -F "objects.charityAction.fields.goalValue.label" "$proof/drift.log" >/dev/null; then
  echo "twenty-test: ERROR: drift diagnostics do not name the field path" >&2
  sed -n '1,120p' "$proof/drift.log" >&2
  exit 1
fi
if ! grep -F "objects.company.fields.leonaidMatchKey.label" "$proof/drift.log" >/dev/null; then
  echo "twenty-test: ERROR: drift on the standard object field was not detected" >&2
  sed -n '1,120p' "$proof/drift.log" >&2
  exit 1
fi
if ! grep -F "ABSICHTLICHER POC-030 DRIFT" "$proof/drift.log" >/dev/null; then
  echo "twenty-test: ERROR: drift diagnostics do not name the current value" >&2
  sed -n '1,120p' "$proof/drift.log" >&2
  exit 1
fi

echo "twenty-test: OK: idempotency, drift and least privilege proven for real"
