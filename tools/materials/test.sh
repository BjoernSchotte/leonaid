#!/bin/sh
# Browser proof for the materials module in the web shell and the 390 px PWA.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  # A borrowed shared stack owns every Docker resource of this run.
  exec python3 "$root/tools/testing/shared_stack.py" core tools/materials/test.sh
fi
leaf=materials-test
module_specs="tests/e2e/modules-materials.spec.mjs"
. "$root/tools/testing/module_browser.sh"

echo "materials-test: OK: versioned uploads, exact old-version download and private access in web and PWA"
