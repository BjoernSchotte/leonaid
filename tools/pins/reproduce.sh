#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
checkout_a="$tmp/checkout-a"
checkout_b="$tmp/checkout-b"
mkdir -p "$checkout_a" "$checkout_b"

git -C "$root" checkout-index --all --prefix="$checkout_a/"
git -C "$root" checkout-index --all --prefix="$checkout_b/"

for checkout in "$checkout_a" "$checkout_b"; do
  rm -f "$checkout/uv.lock" "$checkout/bun.lock"
  docker run --rm \
    -v "$checkout:/workspace" \
    -w /workspace \
    "$UV_IMAGE" \
    uv lock --python 3.13.13
  docker run --rm \
    -v "$checkout:/workspace" \
    -w /workspace \
    "$BUN_IMAGE" \
    bun install --lockfile-only --ignore-scripts
done

for lock in uv.lock bun.lock infra/locks/external-systems.lock; do
  if ! cmp "$checkout_a/$lock" "$checkout_b/$lock"; then
    echo "pin-reproduce: ERROR: two fresh index checkouts differ for $lock" >&2
    exit 1
  fi
  if ! cmp "$root/$lock" "$checkout_a/$lock"; then
    echo "pin-reproduce: ERROR: committed/indexed $lock is stale" >&2
    exit 1
  fi
done

echo "pin-reproduce: OK: two fresh index checkouts produced identical locks"
