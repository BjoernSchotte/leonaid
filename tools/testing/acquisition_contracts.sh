#!/bin/sh
# Browser-free API contracts of acquisition, actions and templates (E-041):
# one borrowed stack, one Golden seed, then every contract in a fixed order
# without a reset. A failure names the contract.
# Usage: acquisition_contracts.sh ROOT [tools/<module>/contract.py ...]
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
[ "$#" -gt 0 ] && shift
if [ "$#" -eq 0 ]; then
  # activity_feed first: the API spends at most 100 Twenty calls a minute,
  # matching and activities use up that budget (activities then waits), and
  # a public order must finish within 8 s. It also needs the Golden Freie
  # Firma still unassigned (assignments assigns it).
  set -- tools/activity_feed/contract.py tools/matching/contract.py \
    tools/assignments/contract.py tools/activities/contract.py \
    tools/actions/contract.py tools/templates/contract.py
fi
if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  # A borrowed shared stack owns every Docker resource of this run.
  exec python3 "$root/tools/testing/shared_stack.py" golden \
    "tools/testing/acquisition_contracts.sh $*"
fi
. "$root/tools/testing/owned_teardown.sh"

env_file="$root/.env.local"
proof=$(mktemp -d)
contract=""

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "acquisition-contracts: FAILED: ${contract:-setup}; diagnostics:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=120 \
      api core-postgres twenty-server twenty-worker >&2 || true
    /bin/sh "$root/tools/ci/capture-failure.sh" \
      "$root" "$proof" "$project" || true
  fi
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

shared_services="api twenty-worker mailpit"
. "$root/tools/testing/borrow_stack.sh"

golden_seed

for contract in "$@"; do
  echo "acquisition-contracts: $contract"
  compose run --rm --user "$(id -u):$(id -g)" --no-deps \
    --env-from-file "$env_file" \
    --env-from-file "$proof/integration.env" \
    --env API_BASE_URL=http://api:8000 \
    --env TWENTY_BASE_URL=http://twenty-server:3000 \
    --env PYTHONPATH=/repo/src:/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --workdir /repo \
    --entrypoint python \
    api "$contract"
done
contract=""

echo "acquisition-contracts: OK: $# contracts on one Golden seed"
