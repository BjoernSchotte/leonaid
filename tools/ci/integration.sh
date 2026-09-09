#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
shard=${1:-all}

case "$shard" in
  all)
    for part in compose seed core documents crm policy pilot-import; do
      /bin/sh "$root/tools/ci/integration.sh" "$part"
    done
    ;;
  compose)
    /bin/sh "$root/tools/compose/test.sh" "$root"
    ;;
  seed)
    /bin/sh "$root/tools/seed/test.sh" "$root"
    ;;
  core)
    /bin/sh "$root/tools/core/test.sh" "$root"
    /bin/sh "$root/tools/schema/test.sh" "$root"
    /bin/sh "$root/tools/outbox/test.sh" "$root"
    ;;
  documents)
    python3 "$root/tools/testing/shared_stack.py" documents \
      tools/storage/test.sh tools/documents/test.sh tools/typst/test.sh
    ;;
  crm)
    /bin/sh "$root/tools/twenty/test.sh" "$root"
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/twenty/gateway_test.sh tools/twenty/import_test.sh
    ;;
  policy)
    /bin/sh "$root/tools/policy/test.sh" "$root"
    ;;
  pilot-import)
    /bin/sh "$root/tools/pilot_import/test.sh" "$root"
    ;;
  *)
    echo "ci-integration: ERROR: unknown shard: $shard" >&2
    exit 64
    ;;
esac

echo "ci-integration: OK: $shard"
