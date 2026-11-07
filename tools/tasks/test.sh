#!/bin/sh
# Browser proof for the tasks module in the web shell and the 390 px PWA.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  # A borrowed shared stack owns every Docker resource of this run.
  exec python3 "$root/tools/testing/shared_stack.py" core tools/tasks/test.sh
fi
leaf=tasks-test
module_specs="tests/e2e/modules-tasks.spec.mjs tests/e2e/tasks-details.spec.mjs
  tests/e2e/tasks-views.spec.mjs tests/e2e/tasks-planning.spec.mjs
  tests/e2e/tasks-ordering.spec.mjs tests/e2e/tasks-structure.spec.mjs
  tests/e2e/tasks-keyboard.spec.mjs tests/e2e/tasks-ordering-faults.spec.mjs"
. "$root/tools/testing/module_browser.sh"

echo "tasks-test: OK: web and PWA task journeys, planning, ordering, structure and details"
