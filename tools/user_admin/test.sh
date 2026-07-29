#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)

/bin/sh "$root/tools/identity/test.sh" "$root"
/bin/sh "$root/tools/invitations/test.sh" "$root"
/bin/sh "$root/tools/sessions/test.sh" "$root"

echo "user-admin-test: OK: Konten, Rollen, Sperre, Sitzungsentzug,"
echo "user-admin-test:     Einladung und E-Mail-Korrektur über reale UI bewiesen"
