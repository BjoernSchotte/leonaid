#!/bin/sh
set -eu
root=$1
mode=${2:-auth}
orders=${3:-false}
case "$orders:$mode" in false:*|true:public-http) ;; *) exit 2 ;; esac
TWENTY_INTEGRATION_API_KEY=
export TWENTY_INTEGRATION_API_KEY
case "$mode" in auth|bootstrap|browser|surface|content|race|isolation|media|media-editor|core-public|public-http|public-media|order-component|migration) ;; *) exit 2 ;; esac
. "$root/infra/locks/images.env"
# Each proof has an independent server-only key; never reuse a parallel stack's.
LEONAID_ORDER_SUBMISSION_KEY=$(docker run --rm --network none "$NODE_IMAGE" \
  node -e 'process.stdout.write(require("node:crypto").randomBytes(32).toString("hex"))')
export LEONAID_ORDER_SUBMISSION_KEY
order_submission_key=$LEONAID_ORDER_SUBMISSION_KEY
if [ "$mode" = order-component ] || [ "$mode" = public-http ] || [ "$mode" = public-media ]; then
  docker run --rm --network none --volume "$root:/workspace:ro" --workdir /workspace \
    "$BUN_IMAGE" bun tools/emdash_spike/order-redisplay-proof.ts
  docker run --rm --network none --volume "$root:/workspace:ro" --workdir /workspace \
    "$BUN_IMAGE" bun tools/emdash_spike/order-presentation-proof.ts
fi
if [ "$mode" = public-http ] || [ "$mode" = public-media ]; then
  docker run --rm --network none --volume "$root:/workspace:ro" --workdir /workspace \
    "$NODE_IMAGE" node tools/emdash_spike/editorial-html-proof.mjs
fi
if [ "$orders" = true ]; then
  docker run --rm --network none --volume "$root:/workspace:ro" "$NODE_IMAGE" \
    node /workspace/tools/emdash_spike/order-subnet.mjs --self-test
  # Read only network topology. Docker atomically rejects a concurrent overlap;
  # never remove another project's networks or reuse their address space.
  EMDASH_ORDER_CRM_SUBNET=$(docker network inspect $(docker network ls -q) | \
    docker run --rm -i --network none --volume "$root:/workspace:ro" "$NODE_IMAGE" \
      node /workspace/tools/emdash_spike/order-subnet.mjs)
  export EMDASH_ORDER_CRM_SUBNET
fi
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
EMDASH_ORDER_API_IMAGE="$project-api"
export EMDASH_ORDER_API_IMAGE
compose() {
  set -- --profile emdash "$@"
  if [ "$orders" = true ]; then
    set -- --file "$root/infra/emdash-spike/orders.test.yml" "$@"
  fi
  if [ "$mode" = migration ]; then
    set -- --file "$root/infra/emdash-spike/import-runtime.test.yml" "$@"
  fi
  if [ "$mode" = media ] || [ "$mode" = media-editor ] || [ "$mode" = public-media ] || [ "$mode" = migration ]; then
    set -- --file "$root/infra/emdash-spike/media-runtime.test.yml" "$@"
  fi
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/emdash-spike/identity.test.yml" \
    --file "$root/infra/emdash-spike/service.test.yml" \
    --file "$root/infra/emdash-spike/core-auth.test.yml" \
    --file "$root/infra/emdash-spike/auth-runtime.test.yml" \
    --file "$root/infra/emdash-spike/bootstrap.test.yml" \
    --file "$root/infra/emdash-spike/login.test.yml" "$@"
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
  rm -f "$proof/sessions.json" "$proof/race-sessions.json" "$proof/reference-sessions.json" "$proof/cms-id" "$proof/root.crt" "$proof/media-http-state.json" "$proof/media-pagination.json" "$proof/public-media.json" "$proof/public-media.png"
  rm -f "$proof/integration.env" "$proof/orders-ui.json"
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
  for(const name of ["api","core-postgres","campaign-site","core-auth-probe","proxy","public","admin-browser","bootstrap-probe","bootstrap-operator","worker","mailpit"]) assert.ok(!services[name].ports?.length);
  assert.deepEqual(Object.keys(services.mailpit.networks),["edge"]);
  assert.deepEqual(Object.keys(services.worker.networks).sort(),["core-data","edge"]);
  assert.equal(services.worker.environment.MAIL_SMTP_HOST,"mailpit");
  assert.equal(services.worker.environment.MAIL_SMTP_PASSWORD,"");
  assert.deepEqual(Object.keys(services["core-auth-probe"].networks),["edge"]);
  assert.deepEqual(Object.keys(services["bootstrap-probe"].networks),["edge"]);
  assert.equal(services["bootstrap-operator"].network_mode,"none");
  const orderKey=services.api.environment.LEONAID_ORDER_SUBMISSION_KEY;
  assert.ok(/^[0-9a-f]{64}$/.test(orderKey));
  for(const [name,service] of Object.entries(services)) {
    const configured=service.environment?.LEONAID_ORDER_SUBMISSION_KEY;
    if(["api","public","campaign-site"].includes(name)) assert.ok(configured===orderKey,"order key wiring mismatch");
    else assert.ok(configured===undefined,"unexpected order key recipient");
  }
  assert.deepEqual(Object.keys(services["admin-browser"].networks),["edge"]);
  assert.ok(!services["campaign-race-probe"].ports?.length);
  for(const name of ["twenty-server","twenty-worker","twenty-postgres","twenty-redis","orders-operator"]) {
    if(services[name]) assert.ok(!services[name].ports?.length);
  }
  if(services["orders-operator"]) {
    assert.deepEqual(Object.keys(services["orders-operator"].networks).sort(),["core-data","edge"]);
    assert.equal(services["orders-operator"].environment.TWENTY_BASE_URL,"http://twenty-server:3000");
  }
  assert.deepEqual(Object.keys(services["campaign-race-probe"].networks).sort(),["cms-data","edge"]);
  const importer=services["krapfentaxi-import-probe"];
  if(importer) {
    assert.ok(!importer.ports?.length);
    assert.deepEqual(Object.keys(importer.networks).sort(),["cms-data","edge"]);
    assert.equal(importer.environment.PGUSER,"emdash");
    assert.equal(importer.environment.PGDATABASE,"emdash");
    for(const key of Object.keys(importer.environment)) assert.ok(!key.startsWith("TWENTY_") && key!=="CORE_POSTGRES_PASSWORD");
  }
  console.log("emdash-auth-runtime: isolated services and Edge-only probe; no host ports");'
compose up --detach --wait core-postgres
compose run --rm --no-deps cms-db-operator
if [ "$mode" = media ] || [ "$mode" = media-editor ] || [ "$mode" = public-media ] || [ "$mode" = migration ]; then
  compose up --detach --wait rustfs
  compose run --rm --no-deps cms-storage-operator
fi
compose up --no-deps --build --detach --wait api campaign-site
fixture() {
  compose run --rm --no-deps --volume "$root:/repo:ro" \
    --volume "$proof:/proof" --user "$(id -u):$(id -g)" \
    --env LEONAID_ORDER_SUBMISSION_KEY="$order_submission_key" \
    --env PYTHONPATH=/repo:/workspace/src --entrypoint python api "$@"
}
probe() {
  compose run --rm --no-deps --volume "$proof:/proof" core-auth-probe \
    bun tools/emdash_spike/auth-runtime-proof.mjs "$@"
}
fixture /repo/tools/seed/golden.py seed-core /repo/tests/fixtures/golden/v1
fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare /proof/sessions.json
if [ "$mode" = order-component ] || [ "$mode" = public-http ]; then
  fixture /repo/tools/emdash_spike/core_order_proxy_proof.py
  LEONAID_ORDER_SUBMISSION_KEY= compose up --no-deps --detach --wait api
  export LEONAID_ORDER_SUBMISSION_KEY="$order_submission_key"
  fixture /repo/tools/emdash_spike/core_order_proxy_proof.py --denied-key
  compose up --no-deps --detach --wait api
  fixture /repo/tools/emdash_spike/core_order_proxy_proof.py
fi
if [ "$mode" = order-component ]; then
  fixture /repo/tools/emdash_spike/core_auth_fixture.py publication-open
  compose up --no-deps --build --detach --wait public proxy
  visual_proof=$(mktemp -d)
  compose run --rm --no-deps --volume "$visual_proof:/visual-proof" admin-browser \
    node tools/emdash_spike/public-order-component-proof.mjs
  fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-mixed-offerings
  compose run --rm --no-deps --volume "$visual_proof:/visual-proof" admin-browser \
    node tools/emdash_spike/public-order-component-proof.mjs --mixed
  echo "public-order-component: synthetic screenshots retained in $visual_proof"
  exit 0
fi
if [ "$mode" = core-public ]; then
  fixture /repo/tools/emdash_spike/core_campaign_proof.py
  exit 0
fi
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
  if [ "$mode" = migration ]; then
    fixture /repo/tools/emdash_spike/core_auth_fixture.py publication-open
    compose run --rm --no-deps --volume "$proof:/proof:ro" krapfentaxi-import-probe
    exit 0
  fi
  if [ "$mode" = public-http ] || [ "$mode" = public-media ]; then
    compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
      node tools/emdash_spike/order-ingress-proof.mjs
    compose up --no-deps --build --detach --wait public
    fixture /repo/tools/emdash_spike/core_auth_fixture.py publication-open
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-runtime-seed.mjs
    public_probe() {
      compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
        node tools/emdash_spike/public-campaign-http-proof.mjs "$@"
    }
    if ! public_probe; then
      compose logs --no-color campaign-site | docker run --rm -i --network none "$NODE_IMAGE" \
        node --input-type=module -e 'let input=""; for await (const chunk of process.stdin) input+=chunk; for (const signal of ["public_campaign_core_unavailable", "public_campaign_content_unavailable", "public_campaign_pipeline_unavailable"]) if(input.includes(signal)) console.log(signal);'
      exit 1
    fi
    if [ "$mode" = public-media ]; then
      compose run --rm --no-deps cms-db-operator node tools/emdash_spike/media-runtime-operator.mjs install
      public_media_probe() {
        compose run --rm --no-deps --volume "$proof:/proof" bootstrap-probe \
          node tools/emdash_spike/public-media-http-proof.mjs "$@"
      }
      public_media_probe
      for storage_fault in bytes mime missing; do
        compose run --rm --no-deps --volume "$proof:/proof:ro" cms-db-operator \
          node tools/emdash_spike/public-media-storage-proof.mjs "$storage_fault"
        public_media_probe --unavailable
        compose run --rm --no-deps --volume "$proof:/proof:ro" cms-db-operator \
          node tools/emdash_spike/public-media-storage-proof.mjs restore
        public_media_probe --ready
      done
      compose run --rm --no-deps --volume "$proof:/proof:ro" campaign-race-probe \
        node tools/emdash_spike/public-database-http-proof.mjs
    fi
    visual_proof=$(mktemp -d)
    compose run --rm --no-deps --volume "$visual_proof:/visual-proof" --volume "$proof:/proof:ro" admin-browser \
      node tools/emdash_spike/public-campaign-browser-proof.mjs
    compose run --rm --no-deps --volume "$visual_proof:/visual-proof" admin-browser \
      node tools/emdash_spike/public-order-component-proof.mjs --campaign
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-mixed-offerings
    compose run --rm --no-deps --volume "$visual_proof:/visual-proof" admin-browser \
      node tools/emdash_spike/public-order-component-proof.mjs --campaign --mixed
    echo "public-campaign: synthetic screenshots retained in $visual_proof"
    if [ "$mode" = public-media ]; then
      compose run --rm --no-deps --volume "$visual_proof:/visual-proof" --volume "$proof:/proof:ro" admin-browser \
        node tools/emdash_spike/krapfentaxi-renderer-browser-proof.mjs
    fi
    if [ "$orders" = true ]; then
      compose up --detach --wait --wait-timeout 420 twenty-server twenty-worker
      compose run --rm --no-deps --user "$(id -u):$(id -g)" --volume "$proof:/proof" orders-operator
      TWENTY_INTEGRATION_API_KEY=$(sed -n 's/^TWENTY_INTEGRATION_API_KEY=//p' "$proof/integration.env")
      export TWENTY_INTEGRATION_API_KEY
      if [ "${#TWENTY_INTEGRATION_API_KEY}" -lt 32 ]; then
        echo "campaign-orders: restricted key missing" >&2
        exit 1
      fi
      compose up --no-deps --detach --wait api
      compose run --rm --no-deps --volume "$proof:/proof" --volume "$visual_proof:/visual-proof" admin-browser \
        node tools/emdash_spike/campaign-orders-browser-proof.mjs
      fixture /repo/tools/emdash_spike/campaign_orders_verify.py
      # Fresh Core rate window, but retain the actual CRM/order records. Burst
      # visitors use distinct synthetic names and command IDs from the paced run.
      compose restart api
      compose up --no-deps --detach --wait api
      compose run --rm --no-deps --volume "$proof:/proof" --volume "$visual_proof:/visual-proof" admin-browser \
        node tools/emdash_spike/campaign-orders-browser-proof.mjs --burst
      # Observation must not consume the tail of the workload's real Twenty
      # quota. Do not change either product limit or mask errors in the burst.
      echo "campaign-orders: burst complete; separating read-only verification from its CRM rate window"
      sleep 60
      fixture /repo/tools/emdash_spike/campaign_orders_verify.py
      LEONAID_ENV=test fixture /repo/tools/emdash_spike/valid_order_ingress_proof.py
      LEONAID_ENV=test fixture /repo/tools/emdash_spike/order_deadline_proof.py
    fi
    for publication_state in none future expired; do
      fixture /repo/tools/emdash_spike/core_auth_fixture.py "publication-$publication_state"
      public_probe --inactive
      if [ "$mode" = public-media ]; then public_media_probe --inactive; fi
    done
    fixture /repo/tools/emdash_spike/core_auth_fixture.py publication-open
    if [ "$mode" = public-media ]; then
      compose stop rustfs
      public_media_probe --unavailable
      compose up --detach --wait rustfs
      public_media_probe --ready
    fi
    compose stop api
    compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
      node tools/emdash_spike/order-ingress-proof.mjs --core-stopped
    public_probe --unavailable
    if [ "$mode" = public-media ]; then public_media_probe --unavailable; fi
    exit 0
  fi
  if [ "$mode" = media ] || [ "$mode" = media-editor ]; then
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-publication
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-isolation
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-runtime-seed.mjs --isolation
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/media-runtime-operator.mjs install
    media_probe() {
      compose run --rm --no-deps --volume "$proof:/proof" bootstrap-probe \
        node tools/emdash_spike/media-http-proof.mjs "$@"
    }
    media_probe
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-reference-races /proof/reference-sessions.json
    compose run --rm --no-deps --volume "$proof:/proof:ro" campaign-race-probe \
      node tools/emdash_spike/campaign-media-reference-proof.mjs
    compose up --no-deps --build --detach --wait public mailpit worker
    if [ "$mode" = media ]; then
      compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
        node tools/emdash_spike/campaign-media-browser-proof.mjs
    fi
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-charity-browser
    compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
      node tools/emdash_spike/campaign-image-create-browser-proof.mjs
    if [ "$mode" = media-editor ]; then
      echo "campaign-editor-pointer: focused browser proof only; full campaign-media-http gate remains required"
      exit 0
    fi
    media_probe --pagination-seed
    compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
      node tools/emdash_spike/campaign-media-pagination-browser-proof.mjs
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/media-runtime-operator.mjs fail-confirm
    media_probe --confirm-failure
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/media-runtime-operator.mjs restore-confirm
    media_probe --confirm-retry
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/media-runtime-operator.mjs tamper
    media_probe --tampered
    compose stop rustfs
    media_probe --storage-down
    compose up --detach --wait rustfs
    media_probe --retained
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-media-races /proof/race-sessions.json
    compose run --rm --no-deps --volume "$proof:/proof:ro" campaign-race-probe \
      node tools/emdash_spike/media-auth-race-proof.mjs
    fixture /repo/tools/emdash_spike/core_auth_fixture.py revoke-charity
    media_probe --revoked
    compose stop api
    media_probe --core-down
    compose up --no-deps --detach --wait api
  fi
  if [ "$mode" = isolation ]; then
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-publication
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-isolation
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-runtime-seed.mjs --isolation
    isolation_probe() {
      compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
        node tools/emdash_spike/campaign-isolation-proof.mjs "$@"
    }
    isolation_probe
    compose up --no-deps --build --detach --wait public mailpit worker
    compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
      node tools/emdash_spike/campaign-editor-browser-proof.mjs --charity --login
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-charity-browser
    compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
      node tools/emdash_spike/campaign-create-browser-proof.mjs --charity-login
    compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
      node tools/emdash_spike/campaign-isolation-browser-proof.mjs
    fixture /repo/tools/emdash_spike/core_auth_fixture.py revoke-charity
    isolation_probe --revoked
  fi
  if [ "$mode" = content ]; then
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-runtime-seed.mjs
    content_probe() {
      compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
        node tools/emdash_spike/campaign-runtime-proof.mjs "$@"
    }
    content_probe
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-races /proof/race-sessions.json
    compose run --rm --no-deps --volume "$proof:/proof:ro" campaign-race-probe \
      node tools/emdash_spike/campaign-auth-race-proof.mjs
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs fail-discard
    content_probe --discard-failure
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore-discard
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs fail-attribution
    content_probe --late-write-failure
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore-attribution
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs disable
    content_probe --guard-unavailable
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs drop-unique
    content_probe --guard-unavailable
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore-unique
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
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs fail-create
    content_probe --create-failure
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs restore-create
    content_probe --create
    fixture /repo/tools/emdash_spike/core_auth_fixture.py revoke
    content_probe --revoked
    compose logs --no-color campaign-site | docker run --rm -i --network none "$NODE_IMAGE" \
      node --input-type=module -e '
      let input=""; for await(const chunk of process.stdin) input+=chunk;
      if (/deferred task failed|Failed to prune revisions|Failed to clean up|Transaction.*(?:complete|committed|rollback)/i.test(input)) throw new Error("CMS transaction/deferred work did not finish cleanly");
      if (!input.includes("Content create error:") || input.includes("LEONAID_SYNTHETIC_CREATE_LOG_CANARY")) throw new Error("CMS creation diagnostic was absent or exposed the database exception");
      console.log("campaign-runtime: real create failure retains fixed signal without database canary");
      console.log("campaign-runtime: no deferred-work or completed-transaction failures");'
  fi
  if [ "$mode" = surface ]; then
    compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
      node tools/emdash_spike/authorization-surface-proof.mjs
  fi
  if [ "$mode" = race ]; then
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-runtime-seed.mjs
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-races /proof/race-sessions.json
    compose run --rm --no-deps --volume "$proof:/proof:ro" campaign-race-probe \
      node tools/emdash_spike/campaign-auth-race-proof.mjs
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
    compose up --no-deps --build --detach --wait mailpit worker
    editor_probe --login
    fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-publication
    compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
      node tools/emdash_spike/campaign-create-browser-proof.mjs
    compose run --rm --no-deps cms-db-operator node tools/emdash_spike/campaign-guard-fixture.mjs trash-created
    compose run --rm --no-deps --volume "$proof:/proof:ro" admin-browser \
      node tools/emdash_spike/campaign-create-browser-proof.mjs --trashed
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
