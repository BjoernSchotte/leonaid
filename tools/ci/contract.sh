#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)

"$root/leonaid" test-pilot-contract
"$root/leonaid" test-pilot-decisions
"$root/leonaid" test-mail-domain
"$root/leonaid" test-pilot-readiness
/bin/sh "$root/tools/openapi/test.sh" "$root"
/bin/sh "$root/tools/testkit/test.sh" "$root"

echo "ci-contract: OK: Pilotplan, Readiness, Entscheidungen, Mail-DNS, OpenAPI und Verträge"
