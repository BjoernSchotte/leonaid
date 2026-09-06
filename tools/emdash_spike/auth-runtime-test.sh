#!/bin/sh
set -eu
root=$1
mode=${2:-auth}
case "$mode" in auth|bootstrap|browser|surface|content) ;; *) exit 2 ;; esac
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
  for(const name of ["api","core-postgres","campaign-site","core-auth-probe","proxy","public","admin-browser","bootstrap-probe","bootstrap-operator"]) assert.ok(!services[name].ports?.length);
  assert.deepEqual(Object.keys(services["core-auth-probe"].networks),["edge"]);
  assert.deepEqual(Object.keys(services["bootstrap-probe"].networks),["edge"]);
  assert.equal(services["bootstrap-operator"].network_mode,"none");
  assert.deepEqual(Object.keys(services["admin-browser"].networks),["edge"]);
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
if [ "$mode" != auth ]; then
  if [ "$mode" = browser ]; then
    docker run --rm --network none --workdir /workspace \
      --volume "$root/apps/public:/workspace/apps/public:ro" \
      --volume "$root/tools:/workspace/tools:ro" "$BUN_IMAGE" \
      bun tools/emdash_spike/return-to-proof.ts
  fi
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
  if [ "$mode" = content ]; then
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-runtime-seed.mjs
    content_probe() {
      compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
        node tools/emdash_spike/campaign-runtime-proof.mjs "$@"
    }
    content_probe
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs fail-discard
    content_probe --discard-failure
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore-discard
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs fail-attribution
    content_probe --late-write-failure
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore-attribution
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs disable
    content_probe --guard-unavailable
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore
    content_probe
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-publication
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/publication-cms-fixture.mjs
    for publication_state in future expired none; do
      fixture /repo/tools/emdash_spike/core_auth_fixture.py "publication-$publication_state"
      content_probe --publish-denied
    done
    fixture /repo/tools/emdash_spike/core_auth_fixture.py publication-open
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs fail-discard
    content_probe --publish-failure
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore-discard
    content_probe --publish
    fixture /repo/tools/emdash_spike/core_auth_fixture.py publication-none
    content_probe --publish-denied
    for publication_state in completed archived; do
      fixture /repo/tools/emdash_spike/core_auth_fixture.py "publication-$publication_state"
      content_probe --publish-denied
    done
    content_probe --prepare-unpublish
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs fail-unpublish
    content_probe --unpublish-failure
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore-unpublish
    content_probe --unpublish
    fixture /repo/tools/emdash_spike/core_auth_fixture.py revoke
    content_probe --revoked
    compose logs --no-color campaign-site | docker run --rm -i --network none "$NODE_IMAGE" \
      node --input-type=module -e '
      let input=""; for await(const chunk of process.stdin) input+=chunk;
      if (/deferred task failed|Failed to prune revisions|Failed to clean up|Transaction.*(?:complete|committed|rollback)/i.test(input)) throw new Error("CMS transaction/deferred work did not finish cleanly");
      console.log("campaign-runtime: no deferred-work or completed-transaction failures");'
  fi
  if [ "$mode" = surface ]; then
    compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
      node tools/emdash_spike/authorization-surface-proof.mjs
  fi
  if [ "$mode" = browser ]; then
    compose up --no-deps --build --detach --wait public
    browser_probe() {
      compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
        node tools/emdash_spike/admin-browser-proof.mjs "$@"
    }
    browser_probe
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-runtime-seed.mjs
    fixture /repo/tools/emdash_spike/core_auth_fixture.py publication-open
    editor_probe() {
      compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
        node tools/emdash_spike/campaign-editor-browser-proof.mjs "$@"
    }
    editor_probe
    fixture /repo/tools/emdash_spike/core_auth_fixture.py revoke
    browser_probe --revoked
    editor_probe --revoked
  fi
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
