#!/bin/sh
set -eu
root=$1
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/emdash-spike/identity.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "emdash-identity-profile: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose --profile '*' down --volumes --remove-orphans >/dev/null || leak_detected=1
  verify_owned_project_removed "$project" || leak_detected=1
  rmdir "$proof"
}
# A teardown leak fails the run even when the test itself passed.
trap 'cleanup; [ "${leak_detected:-0}" -eq 0 ] || exit 1' EXIT
trap 'exit 130' HUP INT TERM
compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" \
  node --input-type=module -e '
  import assert from "node:assert/strict";
  let input=""; for await(const chunk of process.stdin) input+=chunk;
  const {services}=JSON.parse(input);
  for(const name of ["api","core-postgres"]) assert.ok(!services[name].ports?.length);
  assert.deepEqual(Object.keys(services.api.depends_on??{}),[]);
  console.log("emdash-identity-profile: isolated API/SQL, no host ports");'
compose up --detach --wait core-postgres
compose up --no-deps --build --detach --wait api
compose run --rm --user "$(id -u):$(id -g)" --no-deps --volume "$root:/repo:ro" \
  --env PYTHONPATH=/repo:/workspace/src --entrypoint python \
  api /repo/tools/seed/golden.py seed-core /repo/tests/fixtures/golden/v1
compose run --rm --user "$(id -u):$(id -g)" --no-deps --volume "$root:/repo:ro" \
  --env PYTHONPATH=/repo:/workspace/src --entrypoint python \
  api /repo/tools/emdash_spike/identity_profile_proof.py
