#!/bin/sh
# Sourced only after the real importer and three browser publishing journeys.
compose up --detach --wait twenty-postgres
docker volume create --label "com.docker.compose.project=$project" \
  --label com.docker.compose.volume=twenty-server-data \
  "${project}_twenty-server-data" >/dev/null
docker run --rm --network none --volume "$proof:/proof" "$NODE_IMAGE" \
  node -e 'require("node:fs").writeFileSync("/proof/restic-password",require("node:crypto").randomBytes(48).toString("hex"),{mode:0o600})'
overlay_list="$root/infra/emdash-spike/recovery-app.overlays"
LEONAID_COMPOSE_PROJECT="$project" LEONAID_BACKUP_TOPOLOGY=emdash \
  LEONAID_BACKUP_COMPOSE_OVERLAY_LIST="$overlay_list" LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
  LEONAID_BACKUP_REPOSITORY="$proof/repository" LEONAID_BACKUP_PASSWORD_FILE="$proof/restic-password" \
  /bin/sh "$root/tools/backup/backup.sh" "$root"
# Release source runtime resources without deleting the recovery source data.
compose stop proxy public campaign-site api worker mailpit rustfs twenty-postgres core-postgres
recovery_target_prefix=$(choose_recovery_prefix)
LEONAID_RECOVERY_PREFIX=$recovery_target_prefix
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
compose up --no-deps --no-build --detach --wait api campaign-site public mailpit worker proxy
compose run --rm --no-deps admin-browser node tools/emdash_spike/recovery-app-browser-proof.mjs
echo "recovery-app: restored Core login, campaign draft/public content and media rendered; no production activation"
