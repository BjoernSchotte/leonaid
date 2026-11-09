#!/bin/sh
set -eu

# CI selection of EmDash proof cases (./leonaid test-emdash-spike --case).
# Usage: emdash.sh <group> [<group>...]; one CI bin may hold several groups
# (tools/ci/select_suites.py EMDASH_BINS). Every case runs exactly once,
# without retries, so an intermittent failure stays visible.
root=$(cd "$(dirname "$0")/../.." && pwd)

# ./leonaid test-emdash [group...], locally and in CI (E-027); without groups
# every group runs.
if [ "$#" -eq 0 ]; then
  # shellcheck disable=SC2046 # one word per group
  set -- $(python3 "$root/tools/ci/select_suites.py" --list emdash)
fi
if [ "$#" -gt 1 ]; then
  # Leak check after every group, also a failed one (run-shards.sh).
  exec /bin/sh "$root/tools/ci/run-shards.sh" emdash "$root/tools/ci/emdash.sh" "$@"
fi
group=${1:-}

case "$group" in
  krapfentaxi-orders)
    # The commerce half of krapfentaxi-orders. It is also the Krapfentaxi
    # migration proof: it runs the krapfentaxi-migration case (import,
    # three-browser editor, published redirects) unchanged before its order
    # phases (auth-runtime-test.sh mode migration), so that case does not run
    # on its own in CI.
    cases=krapfentaxi-orders-commerce
    ;;
  krapfentaxi-deadlines)
    # The deadline half of krapfentaxi-orders, on its own stack: native and
    # script order deadlines, partial CRM write, Caddy body deadlines.
    cases=krapfentaxi-orders-deadlines
    ;;
  campaign-edge)
    # redirect-aliases: three-browser alias editor on /admin/actions/<id>
    # under the strict CSP. campaign-hosts: a campaign on its own host
    # through the real edge (specs/multi-domain §7, §14), with and then
    # without a general public host, on one stack.
    cases="redirect-aliases campaign-hosts"
    ;;
  static)
    # Stack-free proofs (dependency pins, source fixtures, authorization
    # inventory, release identity/manifest contracts, closed runtime) plus the
    # small database-free proxy/public/CMS routing stack.
    cases="dependencies krapfentaxi-source authorization-inventory release-manifest-compatibility release-legacy-boundary release-image-identity closed-runtime proxy-routing"
    ;;
  *)
    echo "ci-emdash: ERROR: group krapfentaxi-orders|krapfentaxi-deadlines|campaign-edge|static required" >&2
    exit 64
    ;;
esac

for name in $cases; do
  started=$(date +%s)
  "$root/leonaid" test-emdash-spike --case "$name"
  echo "ci-emdash: OK: $name ($(( $(date +%s) - started ))s)"
done
echo "ci-emdash: OK: $group"
