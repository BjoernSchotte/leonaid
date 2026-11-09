#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)

# The same entry point locally and in CI (E-027): ./leonaid test-integration
# [shard...]; without shards every shard of the selector runs, and Contract.
if [ "$#" -eq 0 ]; then
  # shellcheck disable=SC2046 # one word per shard
  set -- $(python3 "$root/tools/ci/select_suites.py" --list integration) contract
fi
# Several shards (one CI bin, tools/ci/select_suites.py): each runs on its own
# fresh stack, in order; a failure does not stop the later shards, the bin
# fails at the end and names every failed shard. tools/ci/leak-check.sh fails
# a shard that leaves Compose objects behind for the next one.
if [ "$#" -gt 1 ]; then
  # Leak check after every shard, also a failed one (run-shards.sh).
  exec /bin/sh "$root/tools/ci/run-shards.sh" integration "$root/tools/ci/integration.sh" "$@"
fi

shard=$1

case "$shard" in
  profiles)
    python3 "$root/tools/testing/shared_stack.py" core tools/compose/profiles.sh
    ;;
  seed-reset)
    if [ -n "${LEONAID_CI_FIXTURE:-}" ]; then
      LEONAID_SEED_PART=reset /bin/sh "$root/tools/seed/test.sh" "$root"
    else
      /bin/sh "$root/tools/seed/test.sh" "$root"
    fi
    ;;
  schema-outbox)
    /bin/sh "$root/tools/schema/test.sh" "$root"
    /bin/sh "$root/tools/outbox/test.sh" "$root"
    ;;
  storage|documents|typst)
    python3 "$root/tools/testing/shared_stack.py" documents \
      "tools/$shard/test.sh"
    ;;
  twenty-install)
    python3 "$root/tools/testing/shared_stack.py" golden tools/twenty/test.sh
    ;;
  crm-gateway)
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/twenty/gateway_test.sh
    ;;
  crm-import)
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/twenty/import_test.sh
    ;;
  api-contract)
    # The live API contract on the fixture (generation and types: Lint)
    # (the required "API contract gate" in ci.yml).
    python3 "$root/tools/testing/shared_stack.py" documents tools/openapi/test.sh
    ;;
  delivery)
    # Delivery windows, completion and deterministic booking/retirement races.
    /bin/sh "$root/tools/delivery/test-foundation.sh"
    ;;
  privacy)
    # Privacy erasure/suppression and the four-eyes legal activation.
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/privacy/test.sh tools/legal_configuration/test.sh
    ;;
  acquisition-contracts)
    # Browser-free API contracts of acquisition, actions and templates.
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/matching/test.sh tools/assignments/test.sh tools/activities/test.sh \
      tools/activity_feed/test.sh tools/actions/test.sh tools/templates/test.sh
    ;;
  policy)
    # On the prepared fixture (Twenty provisioned): the proof is the
    # negative contract, not a cold start; Integration / compose owns that.
    python3 "$root/tools/testing/shared_stack.py" golden tools/policy/test.sh
    ;;
  # OpenAPI and cross-system contracts; rides in an Integration bin.
  contract)
    /bin/sh "$root/tools/ci/contract.sh"
    ;;
  *)
    echo "ci-integration: ERROR: unknown shard: $shard" >&2
    exit 64
    ;;
esac

echo "ci-integration: OK: $shard"
