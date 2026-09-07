#!/bin/sh
set -eu
root=$1
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
EMDASH_ORDER_API_IMAGE=$NODE_IMAGE
EMDASH_RECOVERY_IMAGE_PREFIX=$project
EMDASH_RECOVERY_TWENTY_SKIP_MIGRATIONS=false
EMDASH_ORDER_CRM_SUBNET=$(docker network inspect $(docker network ls -q) | \
  docker run --rm -i --network none --volume "$root:/workspace:ro" "$NODE_IMAGE" \
    node /workspace/tools/emdash_spike/order-subnet.mjs)
LEONAID_RECOVERY_PREFIX=${EMDASH_ORDER_CRM_SUBNET%.0/24}
export EMDASH_ORDER_API_IMAGE EMDASH_RECOVERY_IMAGE_PREFIX EMDASH_RECOVERY_TWENTY_SKIP_MIGRATIONS EMDASH_ORDER_CRM_SUBNET LEONAID_RECOVERY_PREFIX
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/emdash-spike/orders.test.yml" \
    --file "$root/infra/emdash-spike/recovery-app.test.yml" \
    --file "$root/infra/emdash-spike/recovery-orders.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "twenty-startup: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose logs --no-color --tail 2000 twenty-server 2>&1 | \
      docker run --rm -i --network none "$NODE_IMAGE" node --input-type=module -e '
      let raw=""; for await(const part of process.stdin) raw+=part;
      const classes=["QueryFailedError","ConnectionError","TimeoutError","TypeError","ReferenceError","SyntaxError","ValidationError","MigrationError"].filter(name=>raw.includes(name));
      const states=["23505","23502","42P07","42710","42P01","28P01","53300","57P03","08006","ECONNREFUSED","ETIMEDOUT"];
      console.log(JSON.stringify({errorClasses:classes,signals:Object.fromEntries(states.map(code=>[code,raw.split(code).length-1]))}));'
  fi
  compose down --volumes >/dev/null
  rmdir "$proof"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" \
  node --input-type=module -e '
  import assert from "node:assert/strict";
  let raw=""; for await(const part of process.stdin) raw+=part;
  const config=JSON.parse(raw);
  for(const name of ["twenty-server","twenty-worker","twenty-postgres","twenty-redis"]) assert.ok(!config.services[name].ports?.length);
  assert.equal(config.services["twenty-server"].environment.DISABLE_DB_MIGRATIONS,"false");
  assert.equal(config.networks["crm-data"].ipam.config.length,1);
  assert.ok(config.networks["crm-data"].ipam.config[0].subnet.endsWith(".32/28"));
  console.log("twenty-startup: exact recovery CRM pool, own project and no published ports");'
compose up --detach --wait --wait-timeout 420 twenty-server twenty-worker
echo "twenty-startup: actual pinned server, worker, PostgreSQL and Redis healthy from fresh volumes"
