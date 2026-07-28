#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
checkout_a="$tmp/checkout-a"
checkout_b="$tmp/checkout-b"
runner_user="$(id -u):$(id -g)"
mkdir -p "$checkout_a" "$checkout_b"

git -C "$root" checkout-index --all --prefix="$checkout_a/"
git -C "$root" checkout-index --all --prefix="$checkout_b/"

for checkout in "$checkout_a" "$checkout_b"; do
  docker run --rm \
    --user "$runner_user" \
    -e UV_CACHE_DIR=/workspace/.cache/uv \
    -e UV_LINK_MODE=copy \
    -v "$checkout:/workspace" \
    -w /workspace \
    "$UV_IMAGE" \
    uv sync --frozen --no-install-project --python 3.13.13
  docker run --rm \
    --user "$runner_user" \
    -e BUN_INSTALL_CACHE_DIR=/workspace/.cache/bun \
    -v "$checkout:/workspace" \
    -w /workspace \
    "$BUN_IMAGE" \
    bun install --frozen-lockfile --ignore-scripts
done

for lock in uv.lock bun.lock infra/locks/external-systems.lock; do
  if ! cmp "$checkout_a/$lock" "$checkout_b/$lock"; then
    echo "pin-reproduce: ERROR: two isolated index checkouts differ for $lock" >&2
    exit 1
  fi
  if ! cmp "$root/$lock" "$checkout_a/$lock"; then
    echo "pin-reproduce: ERROR: worktree and indexed $lock differ" >&2
    exit 1
  fi
done

echo "pin-reproduce: OK: two isolated index checkouts installed identical frozen locks"
