#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
proof=$(mktemp -d)
cleanup() {
  status=$?
  if [ "${shared_leaf_owned:-false}" = true ]; then
    rmdir "$LEONAID_TEST_STACK/in-use" || status=1
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
shared_services=proxy
. "$root/tools/testing/borrow_stack.sh"
compose --profile '*' up --no-build --detach --wait --wait-timeout 420
for service in mailpit listmonk listmonk-postgres otel-collector; do
  container_id=$(compose ps --quiet "$service")
  test "$(docker inspect --format '{{.State.Health.Status}}' "$container_id")" = healthy
done
compose exec -T api python -c '
import urllib.request
for path in ("mail/readyz", "mailing/health"):
    with urllib.request.urlopen("http://proxy:8080/" + path, timeout=10) as response:
        assert response.status == 200
'
echo 'compose-profiles: optional services healthy and proxy routes reachable'
