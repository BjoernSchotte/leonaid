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
    --file "$root/infra/emdash-spike/identity.test.yml" \
    --file "$root/infra/emdash-spike/core-auth.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "emdash-core-auth: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose unpause api >/dev/null 2>&1 || true
  compose down --volumes >/dev/null
  rm -f "$proof/sessions.json"
  rmdir "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" \
  node --input-type=module -e '
  import assert from "node:assert/strict";
  let input=""; for await(const chunk of process.stdin) input+=chunk;
  const {services}=JSON.parse(input);
  for(const name of ["api","core-postgres","core-auth-probe"]) assert.ok(!services[name].ports?.length);
  assert.deepEqual(Object.keys(services["core-auth-probe"].networks),["edge"]);
  assert.ok(!Object.keys(services["core-auth-probe"].environment??{}).length);
  console.log("emdash-core-auth: no host ports; probe has only Edge access and no configured credentials");'
compose up --detach --wait core-postgres
compose up --no-deps --build --detach --wait api
fixture() {
  compose run --rm --no-deps --volume "$root:/repo:ro" \
    --volume "$proof:/proof" --user "$(id -u):$(id -g)" \
    --env PYTHONPATH=/repo:/workspace/src --entrypoint python api "$@"
}
probe() {
  compose run --rm --no-deps --volume "$proof:/proof:ro" core-auth-probe \
    bun tools/emdash_spike/core-auth-proof.mjs "$@"
}
fixture /repo/tools/seed/golden.py seed-core /repo/tests/fixtures/golden/v1
fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare /proof/sessions.json
probe
fixture /repo/tools/emdash_spike/core_auth_fixture.py revoke
probe --revoked
compose pause api
probe --unavailable
compose unpause api
compose stop api
probe --unavailable
