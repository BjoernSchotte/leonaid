#!/bin/sh
set -eu
root=$1
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/emdash-spike/proxy.test.yml" --profile emdash "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "emdash-proxy-proof: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose down --volumes >/dev/null
  rm -f "$proof/root.crt"
  rmdir "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
docker run --rm --network none \
  --env CADDY_ACME_EMAIL=operator@leonaid.invalid \
  --env LEONAID_PUBLIC_DOMAIN=leonaid.invalid \
  --env TWENTY_PUBLIC_DOMAIN=crm.leonaid.invalid \
  --volume "$root/infra/pilot/Caddyfile:/etc/caddy/Caddyfile:ro" \
  "$CADDY_IMAGE" caddy adapt --config /etc/caddy/Caddyfile \
  --adapter caddyfile --validate >/dev/null
compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" \
  node --input-type=module -e '
  import assert from "node:assert/strict";
  let input=""; for await(const chunk of process.stdin) input+=chunk;
  const {services}=JSON.parse(input);
  for(const name of ["proxy","public","campaign-site"]) assert.ok(!services[name].ports?.length);
  console.log("emdash-proxy-proof: no published ports");'
# Only these real services run; --no-deps avoids starting unrelated stack services.
compose up --no-deps --build --detach public campaign-site
compose up --no-deps --detach --wait proxy
compose cp proxy:/data/caddy/pki/authorities/local/root.crt "$proof/root.crt"
# Public CA certificate only, never the signing key. The CMS runs as Node UID.
chmod 644 "$proof/root.crt"
compose cp "$proof/root.crt" campaign-site:/tmp/proxy-root.crt
compose exec -T --env NODE_EXTRA_CA_CERTS=/tmp/proxy-root.crt campaign-site node /proof/proxy-proof.mjs
compose stop campaign-site
# Reuse the CMS image as a one-shot probe, not as an HTTP server.
compose run --rm --no-deps --volume "$proof/root.crt:/tmp/proxy-root.crt:ro" \
  --env NODE_EXTRA_CA_CERTS=/tmp/proxy-root.crt campaign-site node /proof/proxy-proof.mjs --cms-stopped
