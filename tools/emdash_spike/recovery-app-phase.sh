#!/bin/sh
# Sourced after the imported browser journeys or an explicitly interrupted import.
if [ "$recovery_import" = false ]; then
  compose run --rm --no-deps admin-browser node \
    tools/emdash_spike/recovery-isolation-browser-proof.mjs --prepare
  fixture /repo/tools/emdash_spike/recovery_aliases.py prepare
fi
if [ "$orders" = true ]; then
  . "$root/tools/emdash_spike/recovery-orders-phase.sh"
  recovery_orders_prepare
fi
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
restore_target() {
  LEONAID_BACKUP_SOURCE_PROJECT="$recovery_source" LEONAID_RESTORE_PROJECT="$recovery_target" \
  LEONAID_RESTORE_CMS_IMAGE="$1" \
  LEONAID_RESTORE_CONFIRM="RESTORE:$recovery_target" LEONAID_RESTORE_TOPOLOGY=emdash \
  LEONAID_RESTORE_SCOPE="${2:-full}" \
  LEONAID_RESTORE_START_APP=false LEONAID_RESTORE_COMPOSE_OVERLAY_LIST="$overlay_list" \
  LEONAID_BACKUP_ALLOW_LOCAL_TEST=true LEONAID_BACKUP_REPOSITORY="$proof/repository" \
  LEONAID_BACKUP_PASSWORD_FILE="$proof/restic-password" \
    /bin/sh "$root/tools/backup/restore.sh" "$root"
}
if [ "$cutover_rollback" = true ]; then
  . "$root/tools/emdash_spike/cutover-rollback-phase.sh"
  return
fi
# Release source runtime resources without deleting the recovery source data.
if [ "$orders" = true ]; then compose stop twenty-worker twenty-server twenty-redis; fi
compose stop proxy public campaign-site api worker mailpit rustfs twenty-postgres core-postgres
recovery_target_prefix=$(choose_recovery_prefix)
LEONAID_RECOVERY_PREFIX=$recovery_target_prefix
if [ "$orders" = true ]; then
  EMDASH_RECOVERY_TWENTY_SKIP_MIGRATIONS=true
  export EMDASH_RECOVERY_TWENTY_SKIP_MIGRATIONS
fi
if refusal_output=$(restore_target "$NODE_IMAGE" 2>&1); then
  echo "recovery-image: restore accepted wrong image" >&2
  exit 1
else
  refusal=$?
  [ "$refusal" -eq 1 ] || exit "$refusal"
fi
case "$refusal_output" in
  *"cms-image-preflight: refused; CMS must remain stopped"*) ;;
  *) echo "recovery-image: restore failed for an unexpected reason" >&2; exit 1 ;;
esac
unset refusal_output
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$recovery_target")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$recovery_target")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$recovery_target")" ]; then
  echo "recovery-image: rejected restore created target resources" >&2
  exit 1
fi
echo "recovery-image: actual restore refused wrong image before creating any target resource"
restore_target "${EMDASH_RECOVERY_IMAGE_PREFIX}-campaign-site"
project=$recovery_target
# A wrong image must fail while CMS still has no target container. This is a
# real immutable Node image without the CMS stamp, not a mocked verifier.
if /bin/sh "$root/tools/backup/verify-cms-image.sh" "$root" "$NODE_IMAGE" >/dev/null 2>&1; then
  echo "recovery-image: wrong image accepted" >&2
  exit 1
else
  refusal=$?
  [ "$refusal" -eq 1 ] || exit "$refusal"
fi
[ -z "$(compose ps --all --quiet campaign-site)" ] || {
  echo "recovery-image: CMS container existed before verification" >&2
  exit 1
}
EMDASH_RECOVERY_VERIFIED_CMS_IMAGE=$(/bin/sh "$root/tools/backup/verify-cms-image.sh" \
  "$root" "${EMDASH_RECOVERY_IMAGE_PREFIX}-campaign-site")
export EMDASH_RECOVERY_VERIFIED_CMS_IMAGE
echo "recovery-image: wrong actual image refused with CMS absent; matching image verified and immutable ID selected before activation"
# Reuse exactly the images built before backup, with no seed or CMS schema
# installation on the restore target. Only recovery-import explicitly resumes
# its existing journal after verifying restored state. This is test-only activation;
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
cms_container=$(compose ps --quiet campaign-site)
[ -n "$cms_container" ] && \
  [ "$(docker inspect --format '{{.Image}}' "$cms_container")" = "$EMDASH_RECOVERY_VERIFIED_CMS_IMAGE" ] || {
  echo "recovery-image: running CMS image differs from verified immutable ID" >&2
  exit 1
}
echo "recovery-image: actual restored CMS container runs exactly the verified immutable image"
# The fresh isolated target has its own Caddy CA; HTTPS API probes must trust
# that actual target certificate, never disable certificate verification.
compose cp proxy:/data/caddy/pki/authorities/local/root.crt "$proof/root.crt"
if [ "$recovery_import" = true ]; then
  compose run --rm --no-deps --volume "$proof:/proof:ro" krapfentaxi-import-probe \
    bun tools/emdash_spike/import-recovery-proof.mjs
  compose run --rm --no-deps admin-browser \
    node tools/emdash_spike/krapfentaxi-import-browser-proof.mjs
  echo "import-recovery: resumed restored journal and actual three-browser draft/edit/publish journeys passed; no production activation"
  return
fi
fixture /repo/tools/emdash_spike/recovery_aliases.py verify
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
fixture /repo/tools/emdash_spike/recovery_aliases.py cleanup
# Fresh restored volumes, no seed/reinstall: repeat the complete alias HTTP
# authority, collision, reserved-path, concurrency, replay and revocation suite.
fixture /repo/tools/emdash_spike/alias_http_proof.py
if [ "$orders" = true ]; then
  fixture /repo/tools/emdash_spike/campaign_orders_verify.py --before-recovery
  fixture /repo/tools/emdash_spike/campaign_orders_verify.py
fi
echo "recovery-app: restored Core login, campaign draft/public content and media rendered; no production activation"
