#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
shard=${1:-}

case "$shard" in
  membership)
    python3 "$root/tools/testing/shared_stack.py" golden tools/invitations/test.sh tools/sessions/test.sh
    ;;
  action-templates)
    python3 "$root/tools/testing/shared_stack.py" golden tools/actions/test.sh tools/templates/test.sh
    ;;
  acquisition-management)
    python3 "$root/tools/testing/shared_stack.py" golden tools/assignments/test.sh tools/activities/test.sh
    ;;
  public-catalog)
    python3 "$root/tools/testing/shared_stack.py" golden tools/public_actions/test.sh tools/activity_feed/test.sh
    ;;
  invitations|sessions|matching|assignments|activities|pwa|templates|commitments|invoices)
    python3 "$root/tools/testing/shared_stack.py" golden "tools/$shard/test.sh"
    ;;
  action-admin|public-actions|public-orders|activity-feed)
    directory=$(printf '%s' "$shard" | tr '-' '_')
    python3 "$root/tools/testing/shared_stack.py" golden "tools/$directory/test.sh"
    ;;
  identity)
    python3 "$root/tools/testing/shared_stack.py" core \
      tools/identity/test.sh
    ;;
  acquisition)
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/matching/test.sh \
      tools/assignments/test.sh \
      tools/activities/test.sh \
      tools/pwa/test.sh
    ;;
  actions)
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/actions/test.sh
    ;;
  public)
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/public_actions/test.sh \
      tools/public_orders/test.sh \
      tools/activity_feed/test.sh
    ;;
  *)
    echo "ci-e2e: ERROR: Shard identity|acquisition|actions|public|invoices erforderlich" >&2
    exit 64
    ;;
esac

echo "ci-e2e: OK: $shard"
