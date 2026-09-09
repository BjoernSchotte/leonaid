#!/bin/sh
set -eu
root=$1
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-order-body-$suffix"
export EMDASH_ORDER_BODY_PROOF="$proof"
export EMDASH_ORDER_BODY_IMAGE="$project-public"
EMDASH_ORDER_BODY_SUBNET=$(docker network inspect $(docker network ls -q) | \
  docker run --rm -i --network none --volume "$root:/workspace:ro" "$NODE_IMAGE" \
    node /workspace/tools/emdash_spike/order-subnet.mjs)
export EMDASH_ORDER_BODY_SUBNET
compose() {
  docker compose --project-name "$project" --env-file "$root/infra/locks/images.env" \
    --file "$root/infra/emdash-spike/order-body-transport.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "order-body-transport: project collision; refusing" >&2
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
  assert.ok(config.networks.proof.ipam.config[0].subnet.endsWith("/24"));
  assert.deepEqual(Object.keys(config.services).sort(),["probe","proxy","public"]);
  for(const service of Object.values(config.services)) {
    assert.ok(!service.ports?.length);
    assert.deepEqual(Object.keys(service.networks),["proof"]);
    assert.ok(!service.environment?.CORE_DATABASE_URL);
    assert.ok(!service.environment?.TWENTY_INTEGRATION_API_KEY);
    assert.ok(!service.environment?.LEONAID_ORDER_SUBMISSION_KEY);
  }
  console.log("order-body-transport: actual Astro/Caddy, isolated explicit subnet, no host ports or Core/CRM credentials");'
compose up --build --detach --wait public proxy
compose cp proxy:/data/caddy/pki/authorities/local/root.crt "$proof/root.crt"
compose run --rm --no-deps probe
echo "order-body-transport: focused RPC transport passed; full campaign/Core/Twenty acceptance remains separate"
