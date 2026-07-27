#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

assert_equal() {
  label=$1
  expected=$2
  actual=$3
  if [ "$actual" != "$expected" ]; then
    echo "runtime-version: ERROR: $label expected '$expected', got '$actual'" >&2
    exit 1
  fi
}

python_version=$(docker run --rm "$PYTHON_IMAGE" python --version)
node_version=$(docker run --rm "$NODE_IMAGE" node --version)
bun_version=$(docker run --rm "$BUN_IMAGE" bun --version)
uv_version=$(docker run --rm "$UV_IMAGE" uv --version)
typst_version=$(docker run --rm "$TYPST_IMAGE" --version)

assert_equal python "Python 3.13.13" "$python_version"
assert_equal node "v22.23.0" "$node_version"
assert_equal bun "1.2.19" "$bun_version"
assert_equal uv "uv 0.11.17" "$uv_version"
assert_equal typst "typst 0.13.1 (unknown hash)" "$typst_version"

browser_versions=$(docker run --rm "$PLAYWRIGHT_IMAGE" /bin/bash -lc '
  chromium=$(/ms-playwright/chromium-1181/chrome-linux/chrome --version)
  firefox=$(/ms-playwright/firefox-1489/firefox/firefox --version)
  test -x /ms-playwright/webkit-2191/pw_run.sh
  printf "%s\n%s\nwebkit-revision 2191\n" "$chromium" "$firefox"
')
expected_browsers=$(printf '%s\n%s\n%s' \
  "Chromium 139.0.7258.5 " \
  "Mozilla Firefox 140.0.2" \
  "webkit-revision 2191")
assert_equal browsers "$expected_browsers" "$browser_versions"

echo "runtime-version: OK: Python, Node, Bun, uv, Typst and Playwright browsers"
