#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
shard=${1:-}

case "$shard" in
  identity)
    python3 "$root/tools/testing/shared_stack.py" core \
      tools/identity/test.sh \
      tools/invitations/test.sh \
      tools/sessions/test.sh
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
      tools/actions/test.sh \
      tools/templates/test.sh \
      tools/action_admin/test.sh \
      tools/commitments/test.sh
    ;;
  public)
    python3 "$root/tools/testing/shared_stack.py" golden \
      tools/public_actions/test.sh \
      tools/public_orders/test.sh \
      tools/activity_feed/test.sh
    ;;
  invoices)
    /bin/sh "$root/tools/invoices/test.sh" "$root"
    ;;
  *)
    echo "ci-e2e: ERROR: Shard identity|acquisition|actions|public|invoices erforderlich" >&2
    exit 64
    ;;
esac

echo "ci-e2e: OK: $shard"
