#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)

"$root/leonaid" test-pilot-contract
"$root/leonaid" test-pilot-decisions
"$root/leonaid" test-mail-domain
"$root/leonaid" test-pilot-readiness
python3 "$root/tools/testing/shared_stack.py" golden tools/testkit/test.sh

echo "ci-contract: OK: Pilotplan, Readiness, Entscheidungen, Mail-DNS und Verträge"
