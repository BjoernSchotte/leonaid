#!/bin/sh
set -eu
root=$1
mode=${2:-auth}
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/emdash-spike/identity.test.yml" \
    --file "$root/infra/emdash-spike/service.test.yml" \
    --file "$root/infra/emdash-spike/core-auth.test.yml" \
    --file "$root/infra/emdash-spike/auth-runtime.test.yml" \
    --file "$root/infra/emdash-spike/bootstrap.test.yml" --profile emdash "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "emdash-auth-runtime: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose down --volumes >/dev/null
  rm -f "$proof/sessions.json" "$proof/cms-id" "$proof/root.crt"
  rmdir "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
docker run --rm --network none --volume "$root:/workspace:ro" \
  --workdir /workspace "$NODE_IMAGE" node tools/emdash_spike/auth-patch-proof.mjs
compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" \
  node --input-type=module -e '
  import assert from "node:assert/strict";
  let input=""; for await(const chunk of process.stdin) input+=chunk;
  const {services}=JSON.parse(input);
  for(const name of ["api","core-postgres","campaign-site","core-auth-probe","proxy","bootstrap-probe","bootstrap-operator"]) assert.ok(!services[name].ports?.length);
  assert.deepEqual(Object.keys(services["core-auth-probe"].networks),["edge"]);
  assert.deepEqual(Object.keys(services["bootstrap-probe"].networks),["edge"]);
  assert.equal(services["bootstrap-operator"].network_mode,"none");
  console.log("emdash-auth-runtime: isolated services and Edge-only probe; no host ports");'
compose up --detach --wait core-postgres
compose run --rm --no-deps cms-db-operator
compose up --no-deps --build --detach --wait api campaign-site
fixture() {
  compose run --rm --no-deps --volume "$root:/repo:ro" \
    --volume "$proof:/proof" --user "$(id -u):$(id -g)" \
    --env PYTHONPATH=/repo:/workspace/src --entrypoint python api "$@"
}
probe() {
  compose run --rm --no-deps --volume "$proof:/proof" core-auth-probe \
    bun tools/emdash_spike/auth-runtime-proof.mjs "$@"
}
fixture /repo/tools/seed/golden.py seed-core /repo/tests/fixtures/golden/v1
fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare /proof/sessions.json
if [ "$mode" = bootstrap ]; then
  docker run --rm --network none --volume "$root:/workspace:ro" --workdir /workspace \
    "$NODE_IMAGE" node tools/emdash_spike/bootstrap-control-proof.mjs
  compose up --no-deps --detach --wait proxy
  compose cp proxy:/data/caddy/pki/authorities/local/root.crt "$proof/root.crt"
  tls_probe() {
    compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
      node tools/emdash_spike/bootstrap-runtime-proof.mjs "$@"
  }
  tls_probe --closed
  # Synthetic Golden Dataset system-admin UUID, not an operational account.
  compose run --rm --no-deps bootstrap-operator 10000000-0000-4000-8000-000000000001
  tls_probe --armed
  compose restart campaign-site
  compose up --no-deps --detach --wait campaign-site
  tls_probe --completed
  compose stop core-postgres
  tls_probe --database-unavailable
  exit 0
fi
probe
fixture /repo/tools/emdash_spike/core_auth_fixture.py rename
probe --renamed
fixture /repo/tools/emdash_spike/core_auth_fixture.py revoke
probe --revoked
compose stop api
probe --unavailable
