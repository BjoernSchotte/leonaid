#!/bin/sh
set -eu

# Usage: e2e.sh <shard> [<shard>...]
# Several shards form one CI bin (tools/ci/select_suites.py). Their leaves
# run on one shared stack per fixture kind: tools/testing/shared_stack.py
# restores the stopped fixture volumes before every leaf, so each leaf still
# starts from the identical prepared state. --keep-going runs every leaf even
# after a failure; the bin then fails and the log names the failed leaves.
root=$(cd "$(dirname "$0")/../.." && pwd)

if [ "$#" -eq 0 ]; then
  echo "ci-e2e: ERROR: at least one shard required" >&2
  exit 64
fi

# Prints "<kind> <leaf script>..." for one shard.
leaves() {
  case "$1" in
  membership)
    echo golden tools/invitations/test.sh tools/sessions/test.sh
    ;;
  action-templates)
    echo golden tools/actions/test.sh tools/templates/test.sh
    ;;
  acquisition-management)
    echo golden tools/assignments/test.sh tools/activities/test.sh
    ;;
  public-catalog)
    echo golden tools/public_actions/test.sh tools/activity_feed/test.sh
    ;;
  invitations|sessions|matching|assignments|activities|pwa|templates|commitments|invoices)
    echo golden "tools/$1/test.sh"
    ;;
  action-admin|public-actions|public-orders|activity-feed)
    echo golden "tools/$(printf '%s' "$1" | tr '-' '_')/test.sh"
    ;;
  # Leitsystem shell: tokens, contrast, visual baselines, dashboard, UX gates.
  leitsystem-ui)
    echo golden tools/ui_system/test.sh tools/ux_acceptance/test.sh tools/dashboard/test.sh
    ;;
  operations)
    echo golden tools/operations/test.sh tools/feature_flags/test.sh tools/privacy/test.sh
    ;;
  invoice-flows)
    echo golden tools/invoice_delivery/test.sh tools/invoice_settlements/test.sh
    ;;
  identity)
    echo core tools/identity/test.sh
    ;;
  tasks|materials|knowledge|inbox)
    echo core "tools/$1/test.sh"
    ;;
  acquisition)
    echo golden tools/matching/test.sh tools/assignments/test.sh tools/activities/test.sh tools/pwa/test.sh
    ;;
  actions)
    echo golden tools/actions/test.sh
    ;;
  public)
    echo golden tools/public_actions/test.sh tools/public_orders/test.sh tools/activity_feed/test.sh
    ;;
  *)
    return 1
    ;;
  esac
}

golden=""
core=""
for shard in "$@"; do
  if ! line=$(leaves "$shard"); then
    echo "ci-e2e: ERROR: unknown shard: $shard" >&2
    exit 64
  fi
  kind=${line%% *}
  scripts=${line#* }
  case "$kind" in
    golden) golden="$golden $scripts" ;;
    core) core="$core $scripts" ;;
  esac
done

status=0
# shellcheck disable=SC2086 # one word per leaf script
if [ -n "$golden" ]; then
  python3 "$root/tools/testing/shared_stack.py" --keep-going golden $golden || status=1
fi
# shellcheck disable=SC2086
if [ -n "$core" ]; then
  python3 "$root/tools/testing/shared_stack.py" --keep-going core $core || status=1
fi
if [ "$status" -ne 0 ]; then
  echo "ci-e2e: ERROR: failed leaves in: $*" >&2
  exit 1
fi
echo "ci-e2e: OK: $*"
