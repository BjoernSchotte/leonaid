#!/bin/sh
# Browser proof for knowledge pages and the editor in web and the 390 px PWA.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  # A borrowed shared stack owns every Docker resource of this run.
  exec python3 "$root/tools/testing/shared_stack.py" core tools/knowledge/test.sh
fi
leaf=knowledge-test
module_specs="tests/e2e/modules-knowledge.spec.mjs tests/e2e/knowledge-editor.spec.mjs"
. "$root/tools/testing/module_browser.sh"

echo "knowledge-test: OK: pages, editor formatting under strict CSP, task and material references and sharing"
