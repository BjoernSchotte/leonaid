#!/bin/sh
set -eu

root=${1:-/workspace}
checker="$root/tools/golden/check.py"
fixture="$root/tests/fixtures/golden/v1"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

python "$checker" "$root"

make_case() {
  name=$1
  mkdir -p "$tmp/$name/tests/fixtures/golden/v1" "$tmp/$name/tools/golden"
  cp "$fixture/manifest.json" \
    "$fixture/schema.json" \
    "$fixture/dataset.json" \
    "$fixture/expected.json" \
    "$fixture/README.md" \
    "$tmp/$name/tests/fixtures/golden/v1/"
  cp "$checker" "$tmp/$name/tools/golden/check.py"
}

expect_failure() {
  name=$1
  pattern=$2
  if python "$tmp/$name/tools/golden/check.py" "$tmp/$name" >"$tmp/$name.out" 2>&1; then
    echo "golden-test: ERROR: negative case $name unexpectedly passed" >&2
    exit 1
  fi
  if ! grep -F "$pattern" "$tmp/$name.out" >/dev/null; then
    echo "golden-test: ERROR: $name missed '$pattern'" >&2
    cat "$tmp/$name.out" >&2
    exit 1
  fi
}

make_case broken-reference
sed -i '0,/20000000-0000-4000-8000-000000000001/s//ffffffff-ffff-4fff-8fff-ffffffffffff/' \
  "$tmp/broken-reference/tests/fixtures/golden/v1/dataset.json"
expect_failure broken-reference "unknown action"

make_case real-email
sed -i 's/system-admin@leonaid.invalid/system-admin@example.com/' \
  "$tmp/real-email/tests/fixtures/golden/v1/dataset.json"
expect_failure real-email "non-reserved email domain"

make_case wrong-amount
sed -i '0,/\"amountCents\": 7200/s//\"amountCents\": 7201/' \
  "$tmp/wrong-amount/tests/fixtures/golden/v1/expected.json"
expect_failure wrong-amount "commitment calculations differ"

make_case schema-drift
sed -i '0,/\"schemaVersion\": 1/s//\"schemaVersion\": 2/' \
  "$tmp/schema-drift/tests/fixtures/golden/v1/expected.json"
expect_failure schema-drift "versions differ"

echo "golden-test: OK: positive and four corrupted-dataset cases passed"
