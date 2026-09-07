#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
exec python3 "$root/tools/backup/restore-state.py" locked \
  --target "${LEONAID_RESTORE_PROJECT:-}" -- \
  /bin/sh "$root/tools/backup/restore-body.sh" "$root"
