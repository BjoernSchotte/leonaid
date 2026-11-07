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

# Prints one "<kind> <leaf script>..." line per fixture kind of one shard.
# Kind "own": the script builds and removes its own stack (no shared fixture).
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
    # Admin host + public host on their own stack (specs/multi-domain stage 1).
    echo own tools/multi_host/test.sh
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
  # Short smoke leg (LEONAID_E2E_SMOKE=1, set below): one real login, one
  # list view, one public order; each leaf filters its specs to that test.
  smoke)
    echo golden tools/sessions/test.sh tools/public_orders/test.sh
    echo core tools/tasks/test.sh
    ;;
  *)
    return 1
    ;;
  esac
}

if [ " $* " != " smoke " ] && case " $* " in *" smoke "*) true ;; *) false ;; esac; then
  echo "ci-e2e: ERROR: the smoke leg runs alone (tools/ci/select_suites.py)" >&2
  exit 64
fi
if [ "$*" = smoke ]; then
  export LEONAID_E2E_SMOKE=1
fi

golden=""
core=""
own=""
for shard in "$@"; do
  if ! lines=$(leaves "$shard"); then
    echo "ci-e2e: ERROR: unknown shard: $shard" >&2
    exit 64
  fi
  while read -r kind scripts; do
    case "$kind" in
      golden) golden="$golden $scripts" ;;
      core) core="$core $scripts" ;;
      own) own="$own $scripts" ;;
    esac
  done <<EOF_LEAVES
$lines
EOF_LEAVES
done

status=0
snapshot=$(mktemp)
trap 'rm -f "$snapshot"' EXIT
# Runs one step; tools/ci/leak-check.sh fails it if it left Compose objects.
step() {
  label=$1
  shift
  /bin/sh "$root/tools/ci/leak-check.sh" snapshot "$snapshot"
  step_status=0
  "$@" || step_status=1
  /bin/sh "$root/tools/ci/leak-check.sh" check "$snapshot" "$label" || step_status=1
  if [ "$step_status" -ne 0 ]; then
    echo "ci-e2e: $label FAILED" >&2
    status=1
  fi
}
# shellcheck disable=SC2086 # one word per leaf script
if [ -n "$golden" ]; then
  step "golden leaves" python3 "$root/tools/testing/shared_stack.py" --keep-going golden $golden
fi
# shellcheck disable=SC2086
if [ -n "$core" ]; then
  step "core leaves" python3 "$root/tools/testing/shared_stack.py" --keep-going core $core
fi
for script in $own; do
  started=$(date +%s)
  step "$script" /bin/sh "$root/$script" "$root"
  # Same shape as shared-stack's leaf line (tools/ci/refit_timings.py).
  echo "ci-e2e: own leaf: $script $(($(date +%s) - started))s, exit $step_status"
done
if [ "$status" -ne 0 ]; then
  echo "ci-e2e: ERROR: failed leaves in: $*" >&2
  exit 1
fi
echo "ci-e2e: OK: $*"
