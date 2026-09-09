#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
shard=${1:-all}

case "$shard" in
  all)
    for part in compose seed core schema outbox storage documents typst crm policy; do
      /bin/sh "$root/tools/ci/integration.sh" "$part"
    done
    ;;
  compose)
    /bin/sh "$root/tools/compose/test.sh" "$root"
    ;;
  seed)
    /bin/sh "$root/tools/seed/test.sh" "$root"
    ;;
  seed-cold)
    LEONAID_SEED_PART=cold /bin/sh "$root/tools/seed/test.sh" "$root"
    ;;
  seed-reset)
    if [ -n "${LEONAID_CI_FIXTURE:-}" ]; then
      LEONAID_SEED_PART=reset /bin/sh "$root/tools/seed/test.sh" "$root"
    else
      /bin/sh "$root/tools/seed/test.sh" "$root"
    fi
    ;;
  core)
    /bin/sh "$root/tools/core/test.sh" "$root"
    ;;
  schema)
    /bin/sh "$root/tools/schema/test.sh" "$root"
    ;;
  outbox)
    /bin/sh "$root/tools/outbox/test.sh" "$root"
    ;;
  storage|documents|typst)
    python3 "$root/tools/testing/shared_stack.py" documents \
      "tools/$shard/test.sh"
    ;;
  twenty-install)
    /bin/sh "$root/tools/twenty/test.sh" "$root"
    ;;
  crm-gateway)
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/twenty/gateway_test.sh
    ;;
  crm-import)
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/twenty/import_test.sh
    ;;
  crm)
    for part in twenty-install crm-gateway crm-import; do
      /bin/sh "$root/tools/ci/integration.sh" "$part"
    done
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
