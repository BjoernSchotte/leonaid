#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)

"$root/leonaid" test-pilot-contract
/bin/sh "$root/tools/openapi/test.sh" "$root"
/bin/sh "$root/tools/testkit/test.sh" "$root"

echo "ci-contract: OK: Pilotplan, OpenAPI und systemübergreifende Verträge"
