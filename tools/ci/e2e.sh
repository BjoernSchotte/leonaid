#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
shard=${1:-}

case "$shard" in
  identity)
    /bin/sh "$root/tools/identity/test.sh" "$root"
    /bin/sh "$root/tools/invitations/test.sh" "$root"
    /bin/sh "$root/tools/sessions/test.sh" "$root"
    ;;
  acquisition)
    /bin/sh "$root/tools/matching/test.sh" "$root"
    /bin/sh "$root/tools/assignments/test.sh" "$root"
    /bin/sh "$root/tools/activities/test.sh" "$root"
    /bin/sh "$root/tools/pwa/test.sh" "$root"
    ;;
  actions)
    /bin/sh "$root/tools/actions/test.sh" "$root"
    /bin/sh "$root/tools/templates/test.sh" "$root"
    /bin/sh "$root/tools/action_admin/test.sh" "$root"
    /bin/sh "$root/tools/commitments/test.sh" "$root"
    ;;
  public)
    /bin/sh "$root/tools/public_actions/test.sh" "$root"
    /bin/sh "$root/tools/public_orders/test.sh" "$root"
    /bin/sh "$root/tools/activity_feed/test.sh" "$root"
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
