#!/bin/sh
# Run the shards of one packed CI leg in order: `/bin/sh SCRIPT SHARD` each.
#
# Usage: run-shards.sh LABEL SCRIPT SHARD...
# Every shard runs even after an earlier failure. After every shard, passed
# or failed, tools/ci/leak-check.sh checks for Compose objects the shard left
# behind: a failed shard is the most likely one to skip its teardown. A leak
# fails that shard and removes only its projects, so the next shard starts
# clean. A failed shard stays failed whatever the leak check finds. The leg
# fails at the end and names every failed shard.
set -u

root=$(cd "$(dirname "$0")/../.." && pwd)
if [ "$#" -lt 3 ]; then
  echo "run-shards: ERROR: usage: run-shards.sh LABEL SCRIPT SHARD..." >&2
  exit 64
fi
label=$1
script=$2
shift 2

snapshot=$(mktemp)
trap 'rm -f "$snapshot"' EXIT
failed=""
for shard in "$@"; do
  started=$(date +%s)
  shard_status=0
  /bin/sh "$root/tools/ci/leak-check.sh" snapshot "$snapshot" || shard_status=1
  /bin/sh "$script" "$shard" || shard_status=1
  /bin/sh "$root/tools/ci/leak-check.sh" check "$snapshot" "$shard" || shard_status=1
  if [ "$shard_status" -eq 0 ]; then
    echo "ci-$label: bin: $shard passed ($(($(date +%s) - started))s)"
  else
    echo "ci-$label: bin: $shard FAILED ($(($(date +%s) - started))s)" >&2
    failed="$failed $shard"
  fi
done
if [ -n "$failed" ]; then
  echo "ci-$label: ERROR: failed shards:$failed" >&2
  exit 1
fi
echo "ci-$label: OK: $*"
