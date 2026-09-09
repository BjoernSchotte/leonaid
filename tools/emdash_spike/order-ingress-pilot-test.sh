#!/bin/sh
set -eu
root=$1
case "$2" in Caddyfile|Caddyfile.test) config=$2 ;; *) exit 2 ;; esac
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
export EMDASH_ORDER_INGRESS_ROOT="$root"
export EMDASH_ORDER_INGRESS_CONFIG="$root/infra/pilot/$config"
export EMDASH_ORDER_INGRESS_PROOF="$proof"
. "$root/infra/locks/images.env"
compose() {
  docker compose --project-name "$project" --env-file "$root/infra/locks/images.env" \
    --file "$root/infra/emdash-spike/order-ingress.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "order-ingress-pilot: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose down --volumes >/dev/null
  rm -f "$proof/root.crt"
  rmdir "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" \
  node --input-type=module -e '
  import assert from "node:assert/strict";
  let input=""; for await (const chunk of process.stdin) input+=chunk;
  const config=JSON.parse(input);
  assert.equal(config.networks.proof.internal,true);
  assert.deepEqual(Object.keys(config.services).sort(),["probe","proxy"]);
  for(const service of Object.values(config.services)) {
    assert.ok(!service.ports?.length);
    assert.deepEqual(Object.keys(service.networks),["proof"]);
  }
  console.log("order-ingress-pilot: isolated internal network, two pinned services, no host ports or operational environment");'
compose up --detach --wait proxy
compose cp proxy:/data/caddy/pki/authorities/local/root.crt "$proof/root.crt"
compose run --rm --no-deps probe
echo "order-ingress-pilot: $config passed with local CA and unchanged routing source"
