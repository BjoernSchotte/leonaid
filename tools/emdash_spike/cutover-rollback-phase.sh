#!/bin/sh
# Sourced only after the actual full encrypted source backup has passed.
# This is isolated acceptance, not an unattended production activation policy.
[ "$cutover_rollback:$orders:$recovery" = true:true:true ] || exit 2
source_runtime_identity() {
  for service in api core-postgres twenty-server twenty-worker rustfs public proxy; do
    instance=$(compose ps --quiet "$service")
    if [ -z "$instance" ]; then
      echo "cutover-rollback: required source service missing: $service" >&2
      return 1
    fi
    identity=$(docker inspect --format '{{.Id}} {{.State.Running}}' "$instance") || return 1
    case "$identity" in
      *" true") printf '%s\n' "$identity" ;;
      *) echo "cutover-rollback: required source service not running: $service" >&2; return 1 ;;
    esac
  done
}
source_runtime_before=$(source_runtime_identity)
LEONAID_ENV=test fixture /repo/tools/emdash_spike/cutover_state.py activate
mkdir "$proof/cutover-browser"
compose run --rm --no-deps --volume "$proof/cutover-browser:/proof" \
  --volume "$recovery_visual_proof:/visual-proof" admin-browser \
  node tools/emdash_spike/cutover-browser-proof.mjs --changed
compose run --rm --no-deps --volume "$proof/recovery-orders-browser:/proof" \
  --volume "$recovery_visual_proof:/visual-proof" admin-browser \
  node tools/emdash_spike/campaign-orders-browser-proof.mjs \
    --imported --after-recovery --primary-alias --after-cutover
cp "$proof/recovery-orders-browser/orders-ui.json" "$proof/orders-ui.json"
cp "$proof/orders-ui.json" "$proof/after-cutover-orders.json"
fixture /repo/tools/emdash_spike/campaign_orders_verify.py --after-cutover
fixture /repo/tools/emdash_spike/campaign_orders_verify.py --before-recovery
LEONAID_ENV=test fixture /repo/tools/emdash_spike/cutover_state.py freeze
# Roll back only the primary presentation choice through Core's audited CAS
# command. New orders and operational writers continue in the source stack.
LEONAID_ENV=test fixture /repo/tools/emdash_spike/cutover_state.py rollback
compose stop campaign-site
recovery_target_prefix=$(choose_recovery_prefix)
LEONAID_RECOVERY_PREFIX=$recovery_target_prefix
if rejected_restore=$(restore_target "$NODE_IMAGE" cms 2>&1); then
  echo "cutover-rollback: wrong CMS image accepted" >&2
  exit 1
fi
case "$rejected_restore" in
  *"cms-image-preflight: refused; CMS must remain stopped"*) ;;
  *) echo "cutover-rollback: unexpected preflight refusal" >&2; exit 1 ;;
esac
unset rejected_restore
for resource in container volume network; do
  case "$resource" in
    container) existing=$(docker ps -aq --filter "label=com.docker.compose.project=$recovery_target") ;;
    volume) existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$recovery_target") ;;
    network) existing=$(docker network ls -q --filter "label=com.docker.compose.project=$recovery_target") ;;
  esac
  [ -z "$existing" ] || { echo "cutover-rollback: rejected restore created target resources" >&2; exit 1; }
done
restore_target "${EMDASH_RECOVERY_IMAGE_PREFIX}-campaign-site" cms
project=$recovery_target
[ -z "$(compose ps --all --quiet api twenty-server twenty-worker twenty-postgres public proxy)" ] || exit 1
[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$recovery_target" --filter 'label=com.docker.compose.volume=twenty-server-data')" ] || exit 1
core_tables=$(compose exec -T core-postgres psql \
  --username "${CORE_POSTGRES_USER:-leonaid}" --dbname "${CORE_POSTGRES_DB:-leonaid}" \
  -At -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
[ "$core_tables" = 0 ] || { echo "cutover-rollback: Core data appeared in CMS-only target" >&2; exit 1; }
EMDASH_RECOVERY_VERIFIED_CMS_IMAGE=$(/bin/sh "$root/tools/backup/verify-cms-image.sh" \
  "$root" "${EMDASH_RECOVERY_IMAGE_PREFIX}-campaign-site")
export EMDASH_RECOVERY_VERIFIED_CMS_IMAGE
LEONAID_CUTOVER_SOURCE_EDGE="${recovery_source}_edge"
export LEONAID_CUTOVER_SOURCE_EDGE
cutover_target_active=true
compose config --format json | docker run --rm -i --network none \
  --env LEONAID_CUTOVER_SOURCE_EDGE --env EMDASH_RECOVERY_VERIFIED_CMS_IMAGE \
  "$NODE_IMAGE" node --input-type=module -e '
  import assert from "node:assert/strict";
  let raw=""; for await(const part of process.stdin) raw+=part;
  const {services,networks}=JSON.parse(raw);
  assert.equal(networks.edge.external,true);
  assert.equal(networks.edge.name,process.env.LEONAID_CUTOVER_SOURCE_EDGE);
  assert.equal(services["campaign-site"].image,process.env.EMDASH_RECOVERY_VERIFIED_CMS_IMAGE);
  assert.deepEqual(Object.keys(services["campaign-site"].networks).sort(),["cms-data","edge"]);
  assert.ok(!Object.hasOwn(services["core-postgres"].networks,"edge"));
  assert.equal(services["campaign-site"].environment.PGDATABASE,"emdash");
  assert.equal(services["campaign-site"].environment.PGUSER,"emdash");
  for(const service of Object.values(services)) assert.ok(!service.ports?.length);
  console.log("cutover-rollback: verified CMS image, source Core edge, isolated restored CMS SQL/storage and no host ports");'
# Only the recovered CMS joins the still-live source edge. Target Core/Twenty
# applications are never activated and contain no restored operational data.
compose up --no-deps --no-build --pull never --detach --wait campaign-site
instance=$(compose ps --quiet campaign-site)
[ "$(docker inspect --format '{{.Image}}' "$instance")" = "$EMDASH_RECOVERY_VERIFIED_CMS_IMAGE" ] || exit 1
project=$recovery_source
LEONAID_RECOVERY_PREFIX=$recovery_source_prefix
[ -z "$(compose ps --quiet campaign-site)" ] || exit 1
[ "$(source_runtime_identity)" = "$source_runtime_before" ] || exit 1
compose run --rm --no-deps --volume "$proof/cutover-browser:/proof:ro" \
  --volume "$recovery_visual_proof:/visual-proof" admin-browser \
  node tools/emdash_spike/cutover-browser-proof.mjs --restored
# Prove restored CMS authority is the current source Core, not a stale identity
# database in the recovery target: withdraw/regrant current memberships while
# retaining actual browser sessions, then test both campaigns' private surfaces.
mkdir "$proof/recovery-control"
recovery_authority_name="${project}-recovery-authority"
recovery_authority_project=$project
compose run --rm --no-deps --name "$recovery_authority_name" \
  --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --user "$(id -u):$(id -g)" --env PYTHONPATH=/repo:/workspace/src \
  --entrypoint python api /repo/tools/emdash_spike/recovery_authority.py &
recovery_authority_pid=$!
compose run --rm --no-deps --volume "$proof/recovery-control:/recovery-control" \
  admin-browser node tools/emdash_spike/recovery-app-browser-proof.mjs
wait "$recovery_authority_pid"
recovery_authority_pid=
compose run --rm --no-deps admin-browser node tools/emdash_spike/recovery-isolation-browser-proof.mjs
LEONAID_ENV=test fixture /repo/tools/emdash_spike/cutover_state.py verify
fixture /repo/tools/emdash_spike/campaign_orders_verify.py --before-recovery
fixture /repo/tools/emdash_spike/campaign_orders_verify.py --after-cutover
compose run --rm --no-deps --volume "$proof/recovery-orders-browser:/proof" \
  --volume "$recovery_visual_proof:/visual-proof" admin-browser \
  node tools/emdash_spike/campaign-orders-browser-proof.mjs --after-rollback --legacy-entry
cp "$proof/recovery-orders-browser/orders-ui.json" "$proof/after-rollback-orders.json"
fixture /repo/tools/emdash_spike/campaign_orders_verify.py --after-rollback
fixture /repo/tools/emdash_spike/campaign_orders_verify.py --before-recovery
fixture /repo/tools/emdash_spike/campaign_orders_verify.py --after-cutover
LEONAID_ENV=test fixture /repo/tools/emdash_spike/valid_order_ingress_proof.py
[ "$(source_runtime_identity)" = "$source_runtime_before" ] || exit 1
echo "cutover-rollback: backup then published-CMS primary cutover; newer orders preserved across CMS-only SQL/media restore and audited legacy selection; 24 additional legacy orders and current source Core authority passed"
echo "cutover-rollback: synthetic screenshots retained in $recovery_visual_proof; no production activation"
