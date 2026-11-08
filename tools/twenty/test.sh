#!/bin/sh
set -eu

# On a shared stack (shared_stack.py) whose Twenty is already provisioned:
# the CI fixture or the shared template. Provisioning an empty Twenty is
# proven by building either of them and by the cold `./leonaid reset` in
# tools/seed/test.sh.
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  echo "twenty-test: ERROR: run through tools/testing/shared_stack.py" >&2
  exit 64
fi
env_file="$root/.env.local"
proof=$(mktemp -d)
host_user_id=$(id -u)
host_group_id=$(id -g)

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "twenty-test: diagnostics for the failed real services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=120 twenty-server twenty-worker >&2 || true
  fi
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

shared_services="twenty-server twenty-worker"
. "$root/tools/testing/borrow_stack.sh"

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

echo "twenty-test: repeats provisioning without duplicates or drift"
run_tool check --snapshot-output /proof/first.json
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
