#!/bin/sh
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"
. "$root/tools/testing/phase.sh"
# The test stack's pulled images; else the first leaf pulls them (5-8 s).
stack="$TWENTY_IMAGE $POSTGRES_IMAGE $VALKEY_IMAGE $RUSTFS_IMAGE $MAILPIT_IMAGE $ALPINE_IMAGE"
case ${1:-} in
  toolchains) images="" ;;
  seed) images=$stack ;;
  browser) images="$stack $PLAYWRIGHT_IMAGE" ;;
  # API contract: the images of the API's stack, without the toolchains.
  api-stack) images=$stack ;;
  *) echo 'Expected toolchains, seed, browser or api-stack prefetch profile' >&2; exit 64 ;;
esac
proof=$(mktemp -d)
pids=""
cleanup() {
  status=$?
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
index=0
for reference in $images; do
  index=$((index + 1))
  phase image-prefetch docker pull "$reference" > "$proof/$index.log" 2>&1 &
  pids="$pids $!"
done
if [ "$1" != api-stack ]; then
  phase bootstrap "$root/leonaid" bootstrap
fi
index=0
for pid in $pids; do
  index=$((index + 1))
  if ! wait "$pid"; then cat "$proof/$index.log" >&2; exit 1; fi
  tail -n 1 "$proof/$index.log"
done
pids=""
