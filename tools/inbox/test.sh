#!/bin/sh
# Browser proof for inbox cases in web and the 390 px PWA and for the public
# inquiry form with consent, uncertain transport and the real rate limit.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
if [ -z "${LEONAID_TEST_STACK:-}" ]; then
  # A borrowed shared stack owns every Docker resource of this run.
  exec python3 "$root/tools/testing/shared_stack.py" core tools/inbox/test.sh
fi
leaf=inbox-test
shared_services="api web pwa public proxy rustfs"
module_seed=tools/inbox/module_cases.py
module_specs="tests/e2e/modules-inbox.spec.mjs tests/e2e/inbox-keyboard.spec.mjs tests/e2e/public-inbox-retry.spec.mjs"
. "$root/tools/testing/module_browser.sh"

echo "inbox-test: OK: case list and pane, notes, status, closing with a note, file versions, keyboard, foreign denial and the public form with consent and retry"
