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
    --file "$root/infra/emdash-spike/service.test.yml" --profile emdash "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "emdash-service-proof: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose down --volumes >/dev/null
  rmdir "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
# Consume credential-bearing rendered configuration only in this pipe; print
# assertions, never the configuration itself or Docker container environments.
compose config --format json | docker run --rm -i --network none \
  --volume "$root:/workspace:ro" --workdir /workspace \
  "$NODE_IMAGE" node tools/emdash_spike/service-topology.mjs
compose up --detach --wait core-postgres rustfs
compose run --rm --no-deps cms-db-operator
compose run --rm --no-deps cms-storage-operator
compose up --build --detach --wait campaign-site
compose exec -T campaign-site node -e 'require("node:assert/strict").notEqual(process.getuid(),0)'
compose run --rm --no-deps cms-probe
compose exec -T campaign-site node --input-type=module -e '
  import assert from "node:assert/strict";
  import {createStorage} from "emdash/storage/s3";
  for (const key of ["CORE_POSTGRES_PASSWORD", "RUSTFS_ACCESS_KEY", "RUSTFS_SECRET_KEY"]) assert.equal(process.env[key], undefined);
  const result = await createStorage({}).download("service-proof.txt");
  assert.equal(await new Response(result.body).text(), "retained-media");
  console.log("emdash-runtime-storage: OK: actual CMS image uses scoped credentials and real S3 adapter");
'
compose up --force-recreate --detach --wait campaign-site
compose run --rm --no-deps cms-probe node tools/emdash_spike/service-proof.mjs --existing
compose stop core-postgres
compose run --rm --no-deps cms-probe node tools/emdash_spike/service-proof.mjs --database-down
compose up --detach --wait core-postgres
compose run --rm --no-deps cms-probe node tools/emdash_spike/service-proof.mjs --existing
