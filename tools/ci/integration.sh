#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)

/bin/sh "$root/tools/compose/test.sh" "$root"
/bin/sh "$root/tools/seed/test.sh" "$root"
/bin/sh "$root/tools/core/test.sh" "$root"
/bin/sh "$root/tools/schema/test.sh" "$root"
/bin/sh "$root/tools/outbox/test.sh" "$root"
/bin/sh "$root/tools/twenty/test.sh" "$root"
/bin/sh "$root/tools/twenty/gateway_test.sh" "$root"
/bin/sh "$root/tools/twenty/import_test.sh" "$root"
/bin/sh "$root/tools/policy/test.sh" "$root"

echo "ci-integration: OK: echte Datenbanken, Migrationen, Seed und Adapter"
