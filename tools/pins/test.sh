#!/bin/sh
set -eu

root=${1:-/workspace}
checker="$root/tools/pins/check.py"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

python "$checker" "$root"

make_fixture() {
  name=$1
  fixture="$tmp/$name"
  mkdir -p "$fixture/infra/locks"
  cp "$root/.tool-versions" \
    "$root/bun.lock" \
    "$root/package.json" \
    "$root/pyproject.toml" \
    "$root/renovate.json" \
    "$root/uv.lock" \
    "$fixture/"
  cp "$root/infra/locks/browser-artifacts.lock" \
    "$root/infra/locks/external-systems.lock" \
    "$root/infra/locks/images.env" \
    "$fixture/infra/locks/"
}

expect_failure() {
  name=$1
  pattern=$2
  fixture="$tmp/$name"
  if python "$checker" "$fixture" >"$tmp/$name.out" 2>&1; then
    echo "pin-test: ERROR: negative case $name unexpectedly passed" >&2
    exit 1
  fi
  if ! grep -F "$pattern" "$tmp/$name.out" >/dev/null; then
    echo "pin-test: ERROR: negative case $name missed '$pattern'" >&2
    cat "$tmp/$name.out" >&2
    exit 1
  fi
}

make_fixture latest
sed -i 's/twenty:v2\.24\.0@/twenty:latest@/' \
  "$tmp/latest/infra/locks/external-systems.lock"
expect_failure latest "forbidden latest tag"

make_fixture frontend-range
sed -i 's/\"prettier\": \"3\.6\.2\"/\"prettier\": \"^3.6.2\"/' \
  "$tmp/frontend-range/package.json"
expect_failure frontend-range "is not exactly pinned"

make_fixture python-range
sed -i 's/\"fastapi==0\.116\.1\"/\"fastapi>=0.116.1\"/' \
  "$tmp/python-range/pyproject.toml"
expect_failure python-range "is not exactly pinned with =="

make_fixture python-hash
sed -i 's/hash = \"sha256:[a-f0-9]*\"/hash = \"\"/g' \
  "$tmp/python-hash/uv.lock"
expect_failure python-hash "invalid artifact hash"

echo "pin-test: OK: positive and four policy-rejection cases passed"
