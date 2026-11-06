#!/bin/sh
# Usage: verify-image-digests.sh [ROOT] [BASE_REV]
#
# Every recorded digest in infra/locks/images.env must still be in its
# registry. images.env is generated from external-systems.lock and
# tools/pins/check.py enforces their parity and that every other file agrees
# with the lock, so a new lock entry cannot escape this registry check.
#
# A moved tag alone does not fail: upstream rebuilds (Docker Official Images)
# move tags without a new version, and the old digest stays pullable.
# .github/workflows/pin-drift.yml detects that drift and opens a re-pin PR.
# With BASE_REV, every pin that differs from BASE_REV must also be the digest
# its tag resolves to right now. LEONAID_PIN_ALL_TAGS=1 requires that for all.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
base=${2:-}

set -- verify "$root"
if [ -n "$base" ]; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  git -C "$root" show "$base:infra/locks/images.env" >"$tmp/base-images.env"
  set -- "$@" --base-env "$tmp/base-images.env"
fi
if [ "${LEONAID_PIN_ALL_TAGS:-0}" = 1 ]; then
  set -- "$@" --all-tags
fi
python3 "$root/tools/pins/image_digests.py" "$@"
