#!/bin/sh
set -eu

# CI selection of EmDash proof cases (./leonaid test-emdash-spike --case).
# Usage: emdash.sh <group> [<group>...]; one CI bin may hold several groups
# (tools/ci/select_suites.py EMDASH_BINS). Every case runs exactly once,
# without retries, so an intermittent failure stays visible.
root=$(cd "$(dirname "$0")/../.." && pwd)

if [ "$#" -gt 1 ]; then
  # Leak check after every group, also a failed one (run-shards.sh).
  exec /bin/sh "$root/tools/ci/run-shards.sh" emdash "$root/tools/ci/emdash.sh" "$@"
fi
group=${1:-}

case "$group" in
  krapfentaxi-orders)
    cases=$group
    ;;
  krapfentaxi-migration)
    # redirect-aliases: three-browser alias editor on /admin/actions/<id>
    # under the strict CSP (short case, shares the browser bootstrap).
    # campaign-hosts: a campaign on its own host through the real edge
    # (specs/multi-domain §7, §14).
    cases="krapfentaxi-migration redirect-aliases campaign-hosts"
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
