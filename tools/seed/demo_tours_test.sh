#!/bin/sh
# Proof of ./leonaid demo-tours on a Golden test stack (not wired into CI):
#   python3 tools/testing/shared_stack.py golden tools/seed/demo_tours_test.sh
# Runs the demo seed twice: the second run changes no row, and Dora and
# Emil see exactly their own stops on the delivery board.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  echo "demo-tours-test: ERROR: run it through tools/testing/shared_stack.py golden" >&2
  exit 64
fi
proof=$(mktemp -d)
integration_key=""

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose logs --no-color --tail=120 api core-postgres >&2 || true
  fi
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

shared_services="api"
. "$root/tools/testing/borrow_stack.sh"

tool() {
  compose run --rm --no-deps \
    --user "$(id -u):$(id -g)" --env HOME=/tmp \
    --env-from-file "$root/.env.local" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" \
    --entrypoint python \
    api "/repo/tools/seed/$@"
}

# The Golden core data this demo builds on (no CRM or documents needed).
tool golden.py seed-core /repo/tests/fixtures/golden/v1
tool demo_tours.py
first=$(tool demo_tours_check.py fingerprint)
tool demo_tours.py
second=$(tool demo_tours_check.py fingerprint)
if [ "$first" != "$second" ]; then
  echo "demo-tours-test: ERROR: the second run changed data ($first -> $second)" >&2
  exit 1
fi
echo "demo-tours-test: second run changed nothing"
test "$(tool demo_tours_check.py counts)" = "orders=14 noted=4" || {
  echo "demo-tours-test: ERROR: expected 14 orders, 4 with a driver note" >&2
  exit 1
}
echo "demo-tours-test: 14 orders, 4 driver notes, same after the second run"
tool demo_tours_check.py drivers
# An instance seeded by the version without notes converges in place (ruling 21).
test "$(tool demo_tours_check.py downgrade)" = "orders=14 noted=0"
tool demo_tours.py
third=$(tool demo_tours_check.py fingerprint)
test "$(tool demo_tours_check.py counts)" = "orders=14 noted=4"
tool demo_tours.py
fourth=$(tool demo_tours_check.py fingerprint)
if [ "$third" != "$fourth" ]; then
  echo "demo-tours-test: ERROR: a run after the upgrade changed data" >&2
  exit 1
fi
tool demo_tours_check.py drivers
echo "demo-tours-test: upgrade from the note-less seed converged, then stable"
echo "demo-tours-test: OK"
