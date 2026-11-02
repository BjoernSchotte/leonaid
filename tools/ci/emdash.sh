#!/bin/sh
set -eu

# CI selection of EmDash proof cases (./leonaid test-emdash-spike --case).
# Each group runs on its own runner; every case runs exactly once, without
# retries, so an intermittent failure stays visible.
root=$(cd "$(dirname "$0")/../.." && pwd)
group=${1:-}

case "$group" in
  krapfentaxi-orders|krapfentaxi-migration)
    cases=$group
    ;;
  static)
    # Stack-free proofs: dependency pins, source fixtures, authorization
    # inventory, release identity/manifest contracts and the closed runtime.
    cases="dependencies krapfentaxi-source authorization-inventory release-manifest-compatibility release-legacy-boundary release-image-identity closed-runtime"
    ;;
  *)
    echo "ci-emdash: ERROR: group krapfentaxi-orders|krapfentaxi-migration|static required" >&2
    exit 64
    ;;
esac

for name in $cases; do
  started=$(date +%s)
  "$root/leonaid" test-emdash-spike --case "$name"
  echo "ci-emdash: OK: $name ($(( $(date +%s) - started ))s)"
done
echo "ci-emdash: OK: $group"
