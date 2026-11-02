#!/bin/sh
# Adapt and validate every tracked Caddyfile with the pinned Caddy image.
#
# A Caddy upgrade can drop or move a directive (2.11.7 moved request_body's
# read_timeout into the timeouts handler). Without this gate the proxy only
# fails at container start, deep inside a stack test.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

count=0
for caddyfile in \
  infra/proxy/Caddyfile \
  infra/pilot/Caddyfile \
  infra/pilot/Caddyfile.test \
  infra/observability/pilot/Caddyfile.test; do
  [ -f "$root/$caddyfile" ] || {
    echo "caddyfile-check: ERROR: $caddyfile is missing" >&2
    exit 1
  }
  if ! output=$(docker run --rm --network none \
    --env LEONAID_HTTPS_PORT=8443 \
    --env LEONAID_LAN_HOST=127.0.0.1 \
    --env LEONAID_REMOTE_HOST=127.0.0.1 \
    --env CADDY_ACME_EMAIL=operator@leonaid.invalid \
    --env LEONAID_PUBLIC_DOMAIN=leonaid.invalid \
    --env TWENTY_PUBLIC_DOMAIN=crm.leonaid.invalid \
    --volume "$root/$caddyfile:/etc/caddy/Caddyfile:ro" \
    "$CADDY_IMAGE" caddy adapt --config /etc/caddy/Caddyfile \
    --adapter caddyfile --validate 2>&1 >/dev/null); then
    printf '%s\n' "$output" | grep '"level":"error"' >&2 || printf '%s\n' "$output" >&2
    echo "caddyfile-check: ERROR: $caddyfile is invalid for $CADDY_IMAGE" >&2
    exit 1
  fi
  count=$((count + 1))
done
echo "caddyfile-check: OK: $count Caddyfiles adapt and validate with the pinned Caddy"
