#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)

# Several shards (one CI bin, tools/ci/select_suites.py): each runs on its own
# fresh stack, in order; a failure does not stop the later shards, the bin
# fails at the end and names every failed shard.
if [ "$#" -gt 1 ]; then
  failed=""
  for part in "$@"; do
    started=$(date +%s)
    if /bin/sh "$root/tools/ci/integration.sh" "$part"; then
      echo "ci-integration: bin: $part passed ($(( $(date +%s) - started ))s)"
    else
      echo "ci-integration: bin: $part FAILED ($(( $(date +%s) - started ))s)" >&2
      failed="$failed $part"
    fi
  done
  if [ -n "$failed" ]; then
    echo "ci-integration: ERROR: failed shards:$failed" >&2
    exit 1
  fi
  echo "ci-integration: OK: $*"
  exit 0
fi

shard=${1:-all}

case "$shard" in
  all)
    for part in compose profiles seed core schema outbox storage documents typst crm policy delivery; do
      /bin/sh "$root/tools/ci/integration.sh" "$part"
    done
    ;;
  compose)
    LEONAID_COMPOSE_PART=base /bin/sh "$root/tools/compose/test.sh" "$root"
    ;;
  profiles)
    python3 "$root/tools/testing/shared_stack.py" core tools/compose/profiles.sh
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
  schema-outbox)
    /bin/sh "$root/tools/schema/test.sh" "$root"
    /bin/sh "$root/tools/outbox/test.sh" "$root"
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
  delivery)
    # Delivery windows, completion and deterministic booking/retirement races.
    /bin/sh "$root/tools/delivery/test-foundation.sh"
    ;;
  policy)
    /bin/sh "$root/tools/policy/test.sh" "$root"
    ;;
  # OpenAPI and cross-system contracts; rides in an Integration bin.
  contract)
    /bin/sh "$root/tools/ci/contract.sh"
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
