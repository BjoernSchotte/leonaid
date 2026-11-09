#!/bin/sh
# Live proof of the Twenty kept across leaf resets (decision E-033): three
# leaves in this order on one golden shared stack (tools/ci/integration.sh
# twenty-install).
#   read   seeds and only reads; the next reset must keep Twenty running.
#   write  finds the same twenty-server process, then adds a person outside
#          the Golden rows.
#   reset  finds Twenty restarted and the extra person gone.
set -eu

root=$1
mode=$2
. "$root/tools/testing/owned_teardown.sh"
env_file="$root/.env.local"
proof=$(mktemp -d)
person=6b5f4c1e-2f61-4d7a-9c0e-7e3d2a1b0c99
cleanup() {
  status=$?
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
fail() {
  echo "twenty-keep-test: ERROR: $mode: $1" >&2
  exit 1
}
[ -n "${LEONAID_TEST_STACK:-}" ] || fail "runs only as a shared-stack leaf"
marker="$LEONAID_TEST_STACK/twenty-keep-test"
shared_services="api twenty-worker mailpit"
. "$root/tools/testing/borrow_stack.sh"
golden_seed
started=$(docker inspect --format '{{.State.StartedAt}}' "$(compose ps -q twenty-server)")
crm() {
  compose run --rm --no-deps --user "$(id -u):$(id -g)" \
    --env-from-file "$env_file" --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" --workdir /repo --entrypoint python api -c "
from tools.seed.golden import TwentyClient
client = TwentyClient()
client.authenticate_for_data()
$1"
}

case "$mode" in
  read)
    echo "$started" >"$marker"
    ;;
  write)
    [ -f "$marker" ] || fail "the read leaf must run first"
    [ "$started" = "$(cat "$marker")" ] ||
      fail "twenty-server restarted after a leaf that only read"
    crm "client.write('people', '$person',
    {'name': {'firstName': 'Keep', 'lastName': 'Probe'}}, exists=False)"
    ;;
  reset)
    [ -f "$marker" ] || fail "the read and write leaves must run first"
    [ "$started" != "$(cat "$marker")" ] ||
      fail "Twenty was kept after a leaf added a person"
    crm "assert client.get_record('people', '$person') is None, 'extra person kept'"
    rm -f "$marker"
    ;;
  *)
    fail "unknown mode"
    ;;
esac
echo "twenty-keep-test: OK: $mode"
