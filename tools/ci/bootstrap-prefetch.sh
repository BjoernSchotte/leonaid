#!/bin/sh
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"
. "$root/tools/testing/phase.sh"
case ${1:-} in
  seed) images="$TWENTY_IMAGE" ;;
  browser) images="$TWENTY_IMAGE $PLAYWRIGHT_IMAGE" ;;
  *) echo 'Expected seed or browser prefetch profile' >&2; exit 64 ;;
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
phase bootstrap "$root/leonaid" bootstrap
index=0
for pid in $pids; do
  index=$((index + 1))
  if ! wait "$pid"; then cat "$proof/$index.log" >&2; exit 1; fi
  tail -n 1 "$proof/$index.log"
done
pids=""
