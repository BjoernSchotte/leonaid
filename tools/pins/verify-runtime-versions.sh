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

assert_equal python "Python 3.13.18" "$python_version"
assert_equal node "v22.23.4" "$node_version"
assert_equal bun "1.4.4" "$bun_version"
case "$uv_version" in
  "uv 0.13.6 (x86_64-unknown-linux-musl)" | \
  "uv 0.13.6 (aarch64-unknown-linux-musl)")
    ;;
  *)
    echo "runtime-version: ERROR: uv expected version 0.13.6 for a supported Linux architecture, got '$uv_version'" >&2
    exit 1
    ;;
esac
assert_equal typst "typst 0.13.1 (unknown hash)" "$typst_version"

browser_versions=$(docker run --rm "$PLAYWRIGHT_IMAGE" /bin/bash -lc '
  chromium=$(/ms-playwright/chromium-1248/chrome-linux64/chrome --version)
  firefox=$(/ms-playwright/firefox-1555/firefox/firefox --version 2>/dev/null)
  test -x /ms-playwright/webkit-2370/pw_run.sh
  printf "%s\n%s\nwebkit-revision 2370\n" "$chromium" "$firefox"
')
expected_browsers=$(printf '%s\n%s\n%s' \
  "Google Chrome for Testing 156.0.8078.80 " \
  "Mozilla Firefox 157.0" \
  "webkit-revision 2370")
assert_equal browsers "$expected_browsers" "$browser_versions"

echo "runtime-version: OK: Python, Node, Bun, uv, Typst and Playwright browsers"
