#!/bin/sh
# Sourced only after the real importer and three browser publishing journeys.
if [ "$orders" = true ]; then
  . "$root/tools/emdash_spike/recovery-orders-phase.sh"
  recovery_orders_prepare
fi
compose run --rm --no-deps admin-browser node \
  tools/emdash_spike/recovery-isolation-browser-proof.mjs --prepare
if [ "$orders" = false ]; then
  compose up --detach --wait twenty-postgres
  docker volume create --label "com.docker.compose.project=$project" \
    --label com.docker.compose.volume=twenty-server-data \
    "${project}_twenty-server-data" >/dev/null
fi
docker run --rm --network none --volume "$proof:/proof" "$NODE_IMAGE" \
  node -e 'require("node:fs").writeFileSync("/proof/restic-password",require("node:crypto").randomBytes(48).toString("hex"),{mode:0o600})'
overlay_list="$root/infra/emdash-spike/recovery-app.overlays"
if [ "$orders" = true ]; then overlay_list="$root/infra/emdash-spike/recovery-orders.overlays"; fi
LEONAID_COMPOSE_PROJECT="$project" LEONAID_BACKUP_TOPOLOGY=emdash \
  LEONAID_BACKUP_COMPOSE_OVERLAY_LIST="$overlay_list" LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
  LEONAID_BACKUP_REPOSITORY="$proof/repository" LEONAID_BACKUP_PASSWORD_FILE="$proof/restic-password" \
  /bin/sh "$root/tools/backup/backup.sh" "$root"
# Release source runtime resources without deleting the recovery source data.
if [ "$orders" = true ]; then compose stop twenty-worker twenty-server twenty-redis; fi
compose stop proxy public campaign-site api worker mailpit rustfs twenty-postgres core-postgres
recovery_target_prefix=$(choose_recovery_prefix)
LEONAID_RECOVERY_PREFIX=$recovery_target_prefix
if [ "$orders" = true ]; then
  EMDASH_RECOVERY_TWENTY_SKIP_MIGRATIONS=true
  export EMDASH_RECOVERY_TWENTY_SKIP_MIGRATIONS
fi
LEONAID_BACKUP_SOURCE_PROJECT="$recovery_source" LEONAID_RESTORE_PROJECT="$recovery_target" \
  LEONAID_RESTORE_CONFIRM="RESTORE:$recovery_target" LEONAID_RESTORE_TOPOLOGY=emdash \
  LEONAID_RESTORE_START_APP=false LEONAID_RESTORE_COMPOSE_OVERLAY_LIST="$overlay_list" \
  LEONAID_BACKUP_ALLOW_LOCAL_TEST=true LEONAID_BACKUP_REPOSITORY="$proof/repository" \
  LEONAID_BACKUP_PASSWORD_FILE="$proof/restic-password" \
  /bin/sh "$root/tools/backup/restore.sh" "$root"
project=$recovery_target
# Reuse exactly the images built before backup, with no seed, importer or CMS
# schema installation on the restore target. This is test-only activation;
# the operational release gate is still closed in restore.sh.
if [ "$orders" = true ]; then
  compose config --format json | docker run --rm -i --network none "$NODE_IMAGE" \
    node --input-type=module -e '
    import assert from "node:assert/strict";
    let raw=""; for await(const part of process.stdin) raw+=part;
    const config=JSON.parse(raw);
    assert.equal(config.services["twenty-server"].environment.DISABLE_DB_MIGRATIONS,"true");
    for(const service of Object.values(config.services)) assert.ok(!service.ports?.length);
    assert.equal(config.networks["crm-data"].ipam.config.length,1);
    assert.ok(config.networks["crm-data"].ipam.config[0].subnet.endsWith(".32/28"));
    console.log("recovery-orders: target has no host ports, one isolated CRM pool and Twenty migrations disabled");'
  compose up --no-build --pull never --detach --wait --wait-timeout 420 twenty-server twenty-worker
fi
compose up --no-deps --no-build --detach --wait api campaign-site public mailpit worker proxy
mkdir "$proof/recovery-control"
recovery_authority_name="${project}-recovery-authority"
compose run --rm --no-deps --name "$recovery_authority_name" \
  --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --user "$(id -u):$(id -g)" --env PYTHONPATH=/repo:/workspace/src \
  --entrypoint python api /repo/tools/emdash_spike/recovery_authority.py &
recovery_authority_pid=$!
compose run --rm --no-deps --volume "$proof/recovery-control:/recovery-control" \
  admin-browser node tools/emdash_spike/recovery-app-browser-proof.mjs
wait "$recovery_authority_pid"
recovery_authority_pid=
compose run --rm --no-deps admin-browser node \
  tools/emdash_spike/recovery-isolation-browser-proof.mjs
if [ "$orders" = true ]; then recovery_orders_verify; fi
echo "recovery-app: restored Core login, campaign draft/public content and media rendered; no production activation"
