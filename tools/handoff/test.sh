#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

docker run --rm \
  --volume "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/handoff/check.py /workspace

/bin/sh "$root/tools/dx/test-fresh-checkout.sh" "$root"

echo "handoff-test: OK: Dokumentvertrag und frischer Docker-Checkout bewiesen"
