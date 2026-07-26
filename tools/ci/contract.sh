#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)

/bin/sh "$root/tools/openapi/test.sh" "$root"
/bin/sh "$root/tools/testkit/test.sh" "$root"

echo "ci-contract: OK: OpenAPI und systemübergreifende Verträge"
