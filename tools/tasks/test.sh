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
# CI smoke leg (tools/ci/e2e.sh smoke): one list view only.
module_smoke_grep="admin: S1 compact rows, status undo and concurrent conflict"
# Planning and structure are server rules: tools/tasks/planning_contract.py
# and structure_contract.py (Integration / schema), not browser specs.
module_specs="tests/e2e/modules-tasks.spec.mjs tests/e2e/tasks-details.spec.mjs
  tests/e2e/tasks-views.spec.mjs tests/e2e/tasks-ordering.spec.mjs
  tests/e2e/tasks-keyboard.spec.mjs tests/e2e/tasks-ordering-faults.spec.mjs"
. "$root/tools/testing/module_browser.sh"

echo "tasks-test: OK: web and PWA task journeys, ordering, keyboard and details"
