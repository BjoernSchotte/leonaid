#!/bin/sh
set -eu

# CI selection of EmDash proof cases (./leonaid test-emdash-spike --case).
# Each group runs on its own runner; every case runs exactly once, without
# retries, so an intermittent failure stays visible.
root=$(cd "$(dirname "$0")/../.." && pwd)
group=${1:-}

case "$group" in
  krapfentaxi-orders)
    cases=$group
    ;;
  krapfentaxi-migration)
    # redirect-aliases: three-browser alias editor on /admin/actions/<id>
    # under the strict CSP (short case, shares the browser bootstrap).
    cases="krapfentaxi-migration redirect-aliases"
    ;;
  static)
    # Stack-free proofs (dependency pins, source fixtures, authorization
    # inventory, release identity/manifest contracts, closed runtime) plus the
    # small database-free proxy/public/CMS routing stack.
    cases="dependencies krapfentaxi-source authorization-inventory release-manifest-compatibility release-legacy-boundary release-image-identity closed-runtime proxy-routing"
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
