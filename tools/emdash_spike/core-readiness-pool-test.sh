#!/bin/sh
set -eu
root=$1
. "$root/infra/locks/images.env"
isolated_subnet=$(docker network inspect $(docker network ls -q) | \
  docker run --rm -i --network none --volume "$root:/workspace:ro" "$NODE_IMAGE" \
    node /workspace/tools/emdash_spike/order-subnet.mjs)
EMDASH_TEST_NET_PREFIX=${isolated_subnet%.0/24}
export EMDASH_TEST_NET_PREFIX
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-readiness-$suffix"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/emdash-spike/identity.test.yml" \
    --file "$root/infra/emdash-spike/isolated-networks.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "core-readiness-pool: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose down --volumes >/dev/null
  rmdir "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" \
  node --input-type=module -e '
  import assert from "node:assert/strict";
  let input=""; for await(const chunk of process.stdin) input+=chunk;
  const {services,networks}=JSON.parse(input);
  for(const name of ["api","core-postgres"]) assert.ok(!services[name].ports?.length);
  assert.deepEqual(Object.keys(services.api.depends_on??{}),[]);
  for(const name of ["edge","core-data"]) assert.equal(networks[name].ipam.config.length,1);
  console.log("core-readiness-pool: independent API/SQL project, explicit subnets, no host ports");'
compose up --detach --wait core-postgres
compose up --no-deps --build --detach --wait api
probe() {
  compose run --rm --no-deps --volume "$root:/repo:ro" \
    --env PYTHONPATH=/repo:/workspace/src --entrypoint python \
    api /repo/tools/emdash_spike/core_readiness_pool.py "$@"
}
probe
compose stop core-postgres
probe --database-down
compose up --detach --wait core-postgres
probe
