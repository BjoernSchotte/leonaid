#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

source_project=${LEONAID_BACKUP_SOURCE_PROJECT:-}
target_project=${LEONAID_RESTORE_PROJECT:-}
confirm=${LEONAID_RESTORE_CONFIRM:-}
repository=${LEONAID_BACKUP_REPOSITORY:-}
password_file=${LEONAID_BACKUP_PASSWORD_FILE:-}
credentials_file=${LEONAID_BACKUP_CREDENTIALS_FILE:-}
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
stage=$(mktemp -d)

fail() {
  echo "restore: ERROR: $*" >&2
  exit 1
}

[ -f "$env_file" ] || fail ".env.local fehlt"
[ -n "$source_project" ] || fail "LEONAID_BACKUP_SOURCE_PROJECT fehlt"
[ -n "$target_project" ] || fail "LEONAID_RESTORE_PROJECT fehlt"
[ -n "$repository" ] || fail "LEONAID_BACKUP_REPOSITORY fehlt"
[ -n "$password_file" ] || fail "LEONAID_BACKUP_PASSWORD_FILE fehlt"

cleanup() {
  status=$?
  rm -rf "$stage"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

safety_arguments=""
if [ "${LEONAID_BACKUP_ALLOW_LOCAL_TEST:-false}" = "true" ]; then
  safety_arguments="--allow-local-test"
fi
docker run --rm \
  -v "$root:/workspace:ro" \
  -v "$password_file:/run/secrets/restic-password:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/backup/safety.py restore \
  --source-project "$source_project" \
  --target-project "$target_project" \
  --repository "$repository" \
  --password-file /run/secrets/restic-password \
  --confirm "$confirm" \
  $safety_arguments

if [ -n "$(docker ps -aq \
  --filter "label=com.docker.compose.project=$target_project")" ]; then
  fail "Restore-Ziel besitzt bereits Container"
fi
if [ -n "$(docker volume ls -q \
  --filter "label=com.docker.compose.project=$target_project")" ]; then
  fail "Restore-Ziel besitzt bereits Volumes"
fi

local_repository=false
case "$repository" in
  /*) local_repository=true ;;
esac

restic_run() {
  restic_command=$1
  shift
  if [ "$local_repository" = "true" ]; then
    if [ -n "$credentials_file" ]; then
      [ -f "$credentials_file" ] || fail "Backup-Credentials-Datei fehlt"
      docker run --rm \
        -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
        -e RESTIC_REPOSITORY=/repository \
        --env-file "$credentials_file" \
        -v "$password_file:/run/secrets/restic-password:ro" \
        -v "$stage:/restore" \
        -v "$repository:/repository" \
        "$RESTIC_IMAGE" "$restic_command" "$@"
    else
      docker run --rm \
        -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
        -e RESTIC_REPOSITORY=/repository \
        -v "$password_file:/run/secrets/restic-password:ro" \
        -v "$stage:/restore" \
        -v "$repository:/repository" \
        "$RESTIC_IMAGE" "$restic_command" "$@"
    fi
  else
    if [ -n "$credentials_file" ]; then
      [ -f "$credentials_file" ] || fail "Backup-Credentials-Datei fehlt"
      docker run --rm \
        -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
        -e "RESTIC_REPOSITORY=$repository" \
        --env-file "$credentials_file" \
        -v "$password_file:/run/secrets/restic-password:ro" \
        -v "$stage:/restore" \
        "$RESTIC_IMAGE" "$restic_command" "$@"
    else
      docker run --rm \
        -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
        -e "RESTIC_REPOSITORY=$repository" \
        -v "$password_file:/run/secrets/restic-password:ro" \
        -v "$stage:/restore" \
        "$RESTIC_IMAGE" "$restic_command" "$@"
    fi
  fi
}

restic_run restore latest \
  --host "$source_project" \
  --tag "leonaid-$source_project" \
  --target /restore

backup_root=$(find "$stage" -type f -name manifest.json -print | head -n 1)
[ -n "$backup_root" ] || fail "Backup-Manifest fehlt"
backup_root=$(dirname "$backup_root")

docker run --rm \
  -e "EXPECTED_SOURCE_PROJECT=$source_project" \
  -v "$backup_root:/backup:ro" \
  "$PYTHON_IMAGE" \
  python -c 'import hashlib,json,os,pathlib,sys
p=pathlib.Path("/backup")
m=json.loads((p/"manifest.json").read_text())
if m.get("schemaVersion") != 1 or m.get("sourceProject") != os.environ["EXPECTED_SOURCE_PROJECT"]:
    sys.exit("restore: Backup-Manifest gehört nicht zur erwarteten Quelle")
for name,item in m.get("files",{}).items():
    data=(p/name).read_bytes()
    if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
        sys.exit(f"restore: Prüfsumme weicht ab: {name}")'

for volume in twenty-server-data rustfs-data; do
  docker volume create \
    --label "com.docker.compose.project=$target_project" \
    --label "com.docker.compose.volume=$volume" \
    "${target_project}_$volume" >/dev/null
done
docker run --rm \
  -v "${target_project}_twenty-server-data:/target" \
  -v "$backup_root:/backup:ro" \
  "$ALPINE_IMAGE" \
  tar -C /target -xf /backup/twenty-storage.tar
docker run --rm \
  -v "${target_project}_rustfs-data:/target" \
  -v "$backup_root:/backup:ro" \
  "$ALPINE_IMAGE" \
  tar -C /target -xf /backup/rustfs-data.tar

compose() {
  docker compose \
    --project-name "$target_project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    "$@"
}

compose up --detach --wait --wait-timeout 420 \
  core-postgres twenty-postgres rustfs
compose exec -T core-postgres pg_restore \
  --username "${CORE_POSTGRES_USER:-leonaid}" \
  --dbname "${CORE_POSTGRES_DB:-leonaid}" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  <"$backup_root/core.dump"
compose exec -T twenty-postgres pg_restore \
  --username "${TWENTY_POSTGRES_USER:-twenty}" \
  --dbname "${TWENTY_POSTGRES_DB:-default}" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  <"$backup_root/twenty.dump"

if [ "${LEONAID_RESTORE_START_APP:-true}" = "true" ]; then
  compose --profile dev-mail up --build --detach --wait --wait-timeout 420
fi

echo "restore: OK: $source_project wurde nach $target_project wiederhergestellt"
