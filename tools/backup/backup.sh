#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_COMPOSE_PROJECT:-leonaid}
repository=${LEONAID_BACKUP_REPOSITORY:-}
password_file=${LEONAID_BACKUP_PASSWORD_FILE:-}
credentials_file=${LEONAID_BACKUP_CREDENTIALS_FILE:-}
compose_file="$root/infra/compose/compose.yml"
compose_overlay=${LEONAID_BACKUP_COMPOSE_OVERLAY:-}
compose_overlay_secondary=${LEONAID_BACKUP_COMPOSE_OVERLAY_SECONDARY:-}
env_file=${LEONAID_ENV_FILE:-"$root/.env.local"}
manifest_output=${LEONAID_BACKUP_MANIFEST_OUTPUT:-}
manifest_output_tmp=
stage=$(mktemp -d)
writers_stopped=false
restart_services=""

fail() {
  echo "backup: ERROR: $*" >&2
  exit 1
}

[ -f "$env_file" ] || fail "Environment-Datei fehlt"
[ -n "$repository" ] || fail "LEONAID_BACKUP_REPOSITORY fehlt"
[ -n "$password_file" ] || fail "LEONAID_BACKUP_PASSWORD_FILE fehlt"
if [ -n "$compose_overlay" ]; then
  compose_overlay=$(cd "$(dirname "$compose_overlay")" && pwd)/$(basename "$compose_overlay")
  case "$compose_overlay" in
    "$root"/*) ;;
    *) fail "Backup-Compose-Overlay muss innerhalb des Repositories liegen" ;;
  esac
  [ -f "$compose_overlay" ] || fail "Backup-Compose-Overlay fehlt"
fi
if [ -n "$compose_overlay_secondary" ]; then
  [ -n "$compose_overlay" ] ||
    fail "Sekundäres Backup-Compose-Overlay benötigt ein primäres Overlay"
  compose_overlay_secondary=$(
    cd "$(dirname "$compose_overlay_secondary")" &&
      pwd
  )/$(basename "$compose_overlay_secondary")
  case "$compose_overlay_secondary" in
    "$root"/*) ;;
    *) fail "Sekundäres Backup-Compose-Overlay muss im Repository liegen" ;;
  esac
  [ -f "$compose_overlay_secondary" ] ||
    fail "Sekundäres Backup-Compose-Overlay fehlt"
fi
if [ -n "$manifest_output" ]; then
  case "$manifest_output" in
    /*) ;;
    *) fail "Backup-Manifest-Ausgabe muss absolut sein" ;;
  esac
  [ -d "$(dirname "$manifest_output")" ] ||
    fail "Verzeichnis für Backup-Manifest-Ausgabe fehlt"
  manifest_output_tmp="$manifest_output.tmp.$$"
fi

compose() {
  if [ -n "$compose_overlay_secondary" ]; then
    docker compose \
      --project-name "$project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$compose_overlay" \
      --file "$compose_overlay_secondary" \
      "$@"
  elif [ -n "$compose_overlay" ]; then
    docker compose \
      --project-name "$project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$compose_overlay" \
      "$@"
  else
    docker compose \
      --project-name "$project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      "$@"
  fi
}

cleanup() {
  status=$?
  if [ "$writers_stopped" = "true" ] && [ -n "$restart_services" ]; then
    compose start $restart_services >/dev/null 2>&1 || true
  fi
  if [ -n "$manifest_output_tmp" ]; then
    rm -f "$manifest_output_tmp"
  fi
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
  python /workspace/tools/backup/safety.py backup \
  --project "$project" \
  --repository "$repository" \
  --password-file /run/secrets/restic-password \
  $safety_arguments

local_repository=false
case "$repository" in
  /*)
    local_repository=true
    mkdir -p "$repository"
    ;;
esac

restic_run() {
  restic_command=$1
  shift
  if [ "$local_repository" = "true" ]; then
    if [ -n "$credentials_file" ]; then
      [ -f "$credentials_file" ] || fail "Backup-Credentials-Datei fehlt"
      docker run --rm \
        --user "$(id -u):$(id -g)" \
        -e RESTIC_CACHE_DIR=/tmp/restic-cache \
        -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
        -e RESTIC_REPOSITORY=/repository \
        --env-file "$credentials_file" \
        -v "$password_file:/run/secrets/restic-password:ro" \
        -v "$repository:/repository" \
        -v "$stage:/input:ro" \
        "$RESTIC_IMAGE" "$restic_command" "$@"
    else
      docker run --rm \
        --user "$(id -u):$(id -g)" \
        -e RESTIC_CACHE_DIR=/tmp/restic-cache \
        -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
        -e RESTIC_REPOSITORY=/repository \
        -v "$password_file:/run/secrets/restic-password:ro" \
        -v "$repository:/repository" \
        -v "$stage:/input:ro" \
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
        -v "$stage:/input:ro" \
        "$RESTIC_IMAGE" "$restic_command" "$@"
    else
      docker run --rm \
        -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
        -e "RESTIC_REPOSITORY=$repository" \
        -v "$password_file:/run/secrets/restic-password:ro" \
        -v "$stage:/input:ro" \
        "$RESTIC_IMAGE" "$restic_command" "$@"
    fi
  fi
}

running=$(compose ps --services --filter status=running)
for required in core-postgres twenty-postgres rustfs; do
  echo "$running" | grep -Fx "$required" >/dev/null ||
    fail "Service ist nicht bereit: $required"
done
for service in twenty-server twenty-worker api worker public pwa web proxy; do
  if echo "$running" | grep -Fx "$service" >/dev/null; then
    restart_services="$restart_services $service"
  fi
done

compose stop \
  proxy api worker public pwa web twenty-worker twenty-server \
  >/dev/null
writers_stopped=true

compose exec -T core-postgres pg_dump \
  --username "${CORE_POSTGRES_USER:-leonaid}" \
  --dbname "${CORE_POSTGRES_DB:-leonaid}" \
  --format custom \
  --no-owner \
  --no-privileges \
  >"$stage/core.dump"
compose exec -T twenty-postgres pg_dump \
  --username "${TWENTY_POSTGRES_USER:-twenty}" \
  --dbname "${TWENTY_POSTGRES_DB:-default}" \
  --format custom \
  --no-owner \
  --no-privileges \
  >"$stage/twenty.dump"

docker run --rm \
  -v "${project}_twenty-server-data:/source:ro" \
  -v "$stage:/backup" \
  "$ALPINE_IMAGE" \
  tar -C /source -cf /backup/twenty-storage.tar .
docker run --rm \
  -v "${project}_rustfs-data:/source:ro" \
  -v "$stage:/backup" \
  "$ALPINE_IMAGE" \
  tar -C /source -cf /backup/rustfs-data.tar .

docker run --rm \
  -e "BACKUP_SOURCE_PROJECT=$project" \
  -v "$stage:/backup" \
  "$PYTHON_IMAGE" \
  python -c 'import datetime,hashlib,json,os,pathlib
p=pathlib.Path("/backup")
files={}
for name in ("core.dump","twenty.dump","twenty-storage.tar","rustfs-data.tar"):
    data=(p/name).read_bytes()
    files[name]={"sha256":hashlib.sha256(data).hexdigest(),"size":len(data)}
(p/"manifest.json").write_text(json.dumps({
    "schemaVersion":1,
    "createdAt":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "sourceProject":os.environ["BACKUP_SOURCE_PROJECT"],
    "files":files,
},sort_keys=True,indent=2)+"\n")'

if ! restic_run snapshots >/dev/null 2>&1; then
  restic_run init
fi
restic_run backup \
  --host "$project" \
  --tag "leonaid-$project" \
  --tag poc112 \
  -- /input
restic_run forget \
  --host "$project" \
  --tag "leonaid-$project" \
  --keep-daily 7 \
  --keep-weekly 5 \
  --keep-monthly 12 \
  --keep-yearly 3 \
  --prune
restic_run check --read-data
if [ -n "$manifest_output" ]; then
  umask 077
  cp "$stage/manifest.json" "$manifest_output_tmp"
  chmod 600 "$manifest_output_tmp"
  mv "$manifest_output_tmp" "$manifest_output"
  manifest_output_tmp=
fi

echo "backup: OK: $project konsistent, verschlüsselt und integritätsgeprüft"
