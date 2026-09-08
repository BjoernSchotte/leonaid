#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
shard=${1:-all}

case "$shard" in
  all)
    for part in compose seed core documents crm pilot; do
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
    /bin/sh "$root/tools/storage/test.sh" "$root"
    /bin/sh "$root/tools/documents/test.sh" "$root"
    /bin/sh "$root/tools/typst/test.sh" "$root"
    ;;
  crm)
    /bin/sh "$root/tools/twenty/test.sh" "$root"
    /bin/sh "$root/tools/twenty/gateway_test.sh" "$root"
    /bin/sh "$root/tools/twenty/import_test.sh" "$root"
    ;;
  pilot)
    /bin/sh "$root/tools/pilot_import/test.sh" "$root"
    /bin/sh "$root/tools/policy/test.sh" "$root"
    ;;
  *)
    echo "ci-integration: ERROR: unknown shard: $shard" >&2
    exit 64
    ;;
esac

echo "ci-integration: OK: $shard"
