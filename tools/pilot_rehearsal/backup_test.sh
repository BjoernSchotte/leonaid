#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)

/bin/sh "$root/tools/backup/test.sh" "$root"
/bin/sh "$root/tools/pilot_backup/test.sh" "$root"
