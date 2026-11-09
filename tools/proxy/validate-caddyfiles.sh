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

# Generated files must match their route table (tools/proxy/caddyfiles.py).
python3 "$root/tools/proxy/caddyfiles.py" --root "$root" --check
# Policy guards on the rendered files (CSP tile origin, dev-only test tiles).
python3 "$root/tools/proxy/caddyfiles_test.py"

count=0
# Each split file is checked without and with public-host aliases; Caddy
# needs ", " between the alias addresses.
for entry in \
  infra/proxy/Caddyfile \
  infra/proxy/Caddyfile.split \
  infra/proxy/Caddyfile.admin-only \
  "infra/proxy/Caddyfile.split|www.leonaid.invalid, alt.leonaid.invalid" \
  infra/pilot/Caddyfile \
  infra/pilot/Caddyfile.split \
  "infra/pilot/Caddyfile.split|www.leonaid.invalid, alt.leonaid.invalid" \
  infra/pilot/Caddyfile.admin-only \
  infra/pilot/Caddyfile.test \
  infra/observability/pilot/Caddyfile.test; do
  caddyfile=${entry%%|*}
  aliases=
  case $entry in *"|"*) aliases=${entry#*|} ;; esac
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
    --env LEONAID_ADMIN_DOMAIN=app.leonaid.invalid \
    --env "LEONAID_PUBLIC_DOMAIN_ALIASES=$aliases" \
    --env TWENTY_PUBLIC_DOMAIN=crm.leonaid.invalid \
    --volume "$root/$caddyfile:/etc/caddy/Caddyfile:ro" \
    "$CADDY_IMAGE" caddy adapt --config /etc/caddy/Caddyfile \
    --adapter caddyfile --validate 2>&1 >/dev/null); then
    printf '%s\n' "$output" | grep '"level":"error"' >&2 || printf '%s\n' "$output" >&2
    echo "caddyfile-check: ERROR: $caddyfile is invalid for $CADDY_IMAGE" >&2
    exit 1
  fi
  # BREACH guard: compression only for build assets under fixed prefixes and
  # only for static asset types; never for HTML, JSON or dynamic routes.
  if ! docker run --rm --network none \
    --env LEONAID_HTTPS_PORT=8443 \
    --env LEONAID_LAN_HOST=127.0.0.1 \
    --env LEONAID_REMOTE_HOST=127.0.0.1 \
    --env CADDY_ACME_EMAIL=operator@leonaid.invalid \
    --env LEONAID_PUBLIC_DOMAIN=leonaid.invalid \
    --env LEONAID_ADMIN_DOMAIN=app.leonaid.invalid \
    --env "LEONAID_PUBLIC_DOMAIN_ALIASES=$aliases" \
    --env TWENTY_PUBLIC_DOMAIN=crm.leonaid.invalid \
    --volume "$root/$caddyfile:/etc/caddy/Caddyfile:ro" \
    "$CADDY_IMAGE" caddy adapt --config /etc/caddy/Caddyfile \
    --adapter caddyfile 2>/dev/null |
    python3 "$root/tools/proxy/encode_scope.py" "$caddyfile"; then
    exit 1
  fi
  count=$((count + 1))
done

# The dev Caddyfile imports uncommitted snippets from .local/dev/caddy.d (see
# infra/compose/README.md). Prove that the import point accepts a typical
# snippet: a static single-page app under its own path with the strict policy.
local_snippets=$(mktemp -d)
trap 'rm -rf "$local_snippets"' EXIT
cat >"$local_snippets/example.caddy" <<'SNIPPET'
handle_path /example/* {
	import leonaid_headers
	root * /srv/local-static/example
	try_files {path} /index.html
	file_server
}
SNIPPET
chmod 0755 "$local_snippets"
chmod 0644 "$local_snippets/example.caddy"
if ! output=$(docker run --rm --network none \
  --env LEONAID_HTTPS_PORT=8443 \
  --env LEONAID_LAN_HOST=127.0.0.1 \
  --env LEONAID_REMOTE_HOST=127.0.0.1 \
  --volume "$root/infra/proxy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  --volume "$local_snippets:/etc/caddy/local.d:ro" \
  "$CADDY_IMAGE" caddy adapt --config /etc/caddy/Caddyfile \
  --adapter caddyfile --validate 2>&1); then
  printf '%s\n' "$output" | grep '"level":"error"' >&2 || printf '%s\n' "$output" >&2
  echo "caddyfile-check: ERROR: infra/proxy/Caddyfile rejects a local dev snippet" >&2
  exit 1
fi
case $output in
  *'"root":"/srv/local-static/example"'*) ;;
  *)
    echo "caddyfile-check: ERROR: infra/proxy/Caddyfile did not import the local dev snippet" >&2
    exit 1
    ;;
esac
count=$((count + 1))
echo "caddyfile-check: OK: $count Caddyfile configurations adapt and validate with the pinned Caddy"
