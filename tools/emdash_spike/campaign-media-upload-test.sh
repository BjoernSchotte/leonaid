#!/bin/sh
set -eu
root=$1
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/emdash-spike/media.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "campaign-media-upload: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose down --volumes >/dev/null
  rmdir "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
# Parse configuration in memory; never print credential-bearing config.
compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" node --input-type=module -e '
  import assert from "node:assert/strict";
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const config = JSON.parse(input);
  assert.ok(Object.values(config.services).every(service => !service.ports?.length));
  const probe = config.services.proof;
  assert.ok(!Object.keys(probe.environment).some(key => ["CORE_POSTGRES_PASSWORD", "RUSTFS_ACCESS_KEY", "RUSTFS_SECRET_KEY"].includes(key)));
  assert.ok(probe.volumes.every(volume => volume.read_only && volume.target !== "/workspace"));
  assert.equal(probe.environment.PGUSER, "emdash");
  assert.equal(probe.environment.PGDATABASE, "emdash");
  assert.ok(!Object.hasOwn(probe.networks, "core-data"));
  console.log("campaign-media-upload: isolated no-host-port topology and scoped probe credentials verified");
'
compose up --detach --wait core-postgres rustfs
compose run --rm --no-deps cms-db-operator
compose run --rm --no-deps cms-storage-operator
compose run --rm --no-deps proof
compose restart core-postgres rustfs
compose up --detach --wait core-postgres rustfs
compose run --rm --no-deps proof node tools/emdash_spike/campaign-media-upload-proof.mjs --existing
