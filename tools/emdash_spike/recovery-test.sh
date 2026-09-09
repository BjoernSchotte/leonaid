#!/bin/sh
set -eu
root=$1
. "$root/infra/locks/images.env"
docker run --rm --network none --volume "$root:/workspace:ro" --workdir /workspace \
  "$NODE_IMAGE" node tools/emdash_spike/recovery-key-proof.mjs
docker run --rm --network none --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" --workdir /workspace \
  "$PYTHON_IMAGE" python tools/backup/manifest_test.py
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
source_project="leonaid-poc112-$suffix"
target_project="leonaid-restore-$suffix"
overlay="$root/infra/emdash-spike/recovery.test.yml"
choose_prefix() {
  subnet=$(docker network inspect $(docker network ls -q) | \
    docker run --rm -i --network none --volume "$root:/workspace:ro" "$NODE_IMAGE" \
      node /workspace/tools/emdash_spike/order-subnet.mjs)
  printf '%s' "${subnet%.0/24}"
}
source_prefix=$(choose_prefix)
target_prefix=$source_prefix
for project in "$source_project" "$target_project"; do
  if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] ||
     [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] ||
     [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
    rmdir "$proof"
    echo "recovery: project collision; refusing" >&2
    exit 1
  fi
done
compose() {
  project=$1
  shift
  if [ "$project" = "$source_project" ]; then prefix=$source_prefix; else prefix=$target_prefix; fi
  LEONAID_RECOVERY_PREFIX="$prefix" docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" --file "$overlay" \
    --file "$root/infra/backup/cms-operators.yml" "$@"
}
cleanup() {
  compose "$source_project" --profile recovery-test --profile emdash down --volumes >/dev/null
  compose "$target_project" --profile recovery-test --profile emdash down --volumes >/dev/null
  # This directory is the freshly allocated private proof, never a project root.
  rm -rf "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
docker run --rm --network none --volume "$proof:/proof" "$NODE_IMAGE" \
  node -e 'require("node:fs").writeFileSync("/proof/password",require("node:crypto").randomBytes(48).toString("hex"),{mode:0o600})'
compose "$source_project" up --detach --wait core-postgres twenty-postgres rustfs
compose "$source_project" run --rm --no-deps recovery-node tools/emdash_spike/service-provision.mjs
compose "$source_project" run --rm --no-deps recovery-node tools/emdash_spike/campaign-runtime-seed.mjs
compose "$source_project" run --rm --no-deps recovery-node tools/emdash_spike/recovery-state-seed.mjs seed
compose "$source_project" run --rm --no-deps --volume "$proof:/proof" recovery-python \
  tools/emdash_spike/recovery-inventory.py seed /proof/before.json
LEONAID_RECOVERY_PREFIX="$source_prefix" LEONAID_COMPOSE_PROJECT="$source_project" LEONAID_BACKUP_TOPOLOGY=emdash \
  LEONAID_BACKUP_COMPOSE_OVERLAY="$overlay" LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
  LEONAID_BACKUP_REPOSITORY="$proof/repository" LEONAID_BACKUP_PASSWORD_FILE="$proof/password" \
  /bin/sh "$root/tools/backup/backup.sh" "$root"
target_prefix=$(choose_prefix)
LEONAID_RECOVERY_PREFIX="$target_prefix" LEONAID_BACKUP_SOURCE_PROJECT="$source_project" LEONAID_RESTORE_PROJECT="$target_project" \
  LEONAID_RESTORE_CONFIRM="RESTORE:$target_project" LEONAID_RESTORE_TOPOLOGY=emdash \
  LEONAID_RESTORE_START_APP=false LEONAID_RESTORE_COMPOSE_OVERLAY="$overlay" \
  LEONAID_BACKUP_ALLOW_LOCAL_TEST=true LEONAID_BACKUP_REPOSITORY="$proof/repository" \
  LEONAID_BACKUP_PASSWORD_FILE="$proof/password" \
  /bin/sh "$root/tools/backup/restore.sh" "$root"
compose "$target_project" run --rm --no-deps recovery-node tools/emdash_spike/recovery-state-seed.mjs verify
compose "$target_project" run --rm --no-deps --volume "$proof:/proof:ro" recovery-python \
  tools/emdash_spike/recovery-inventory.py verify /proof/before.json
echo "recovery: encrypted local Restic SQL/media round trip passed; HTTP/login/release gates remain open"
