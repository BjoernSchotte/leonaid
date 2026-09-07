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
compose_overlay=${LEONAID_RESTORE_COMPOSE_OVERLAY:-}
compose_overlay_secondary=${LEONAID_RESTORE_COMPOSE_OVERLAY_SECONDARY:-}
env_file=${LEONAID_ENV_FILE:-"$root/.env.local"}
topology=${LEONAID_RESTORE_TOPOLOGY:-legacy}
case "$topology" in legacy|emdash) ;; *) echo "restore: ERROR: unknown topology" >&2; exit 1 ;; esac
restore_no_build=${LEONAID_RESTORE_NO_BUILD:-false}
restore_profile=${LEONAID_RESTORE_PROFILE:-dev-mail}
stage=$(mktemp -d)

fail() {
  echo "restore: ERROR: $*" >&2
  exit 1
}

[ -f "$env_file" ] || fail "Environment-Datei fehlt"
[ -n "$source_project" ] || fail "LEONAID_BACKUP_SOURCE_PROJECT fehlt"
[ -n "$target_project" ] || fail "LEONAID_RESTORE_PROJECT fehlt"
[ -n "$repository" ] || fail "LEONAID_BACKUP_REPOSITORY fehlt"
[ -n "$password_file" ] || fail "LEONAID_BACKUP_PASSWORD_FILE fehlt"
if [ -n "$compose_overlay" ]; then
  compose_overlay=$(cd "$(dirname "$compose_overlay")" && pwd)/$(basename "$compose_overlay")
  case "$compose_overlay" in
    "$root"/*) ;;
    *) fail "Restore-Compose-Overlay muss innerhalb des Repositories liegen" ;;
  esac
  [ -f "$compose_overlay" ] || fail "Restore-Compose-Overlay fehlt"
fi
if [ -n "$compose_overlay_secondary" ]; then
  [ -n "$compose_overlay" ] ||
    fail "Sekundäres Restore-Compose-Overlay benötigt ein primäres Overlay"
  compose_overlay_secondary=$(
    cd "$(dirname "$compose_overlay_secondary")" &&
      pwd
  )/$(basename "$compose_overlay_secondary")
  case "$compose_overlay_secondary" in
    "$root"/*) ;;
    *) fail "Sekundäres Restore-Compose-Overlay muss im Repository liegen" ;;
  esac
  [ -f "$compose_overlay_secondary" ] ||
    fail "Sekundäres Restore-Compose-Overlay fehlt"
fi

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

compose() {
  if [ "$topology" = emdash ]; then
    set -- --file "$root/infra/backup/cms-operators.yml" "$@"
  fi
  if [ -n "$compose_overlay_secondary" ]; then
    docker compose \
      --project-name "$target_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$compose_overlay" \
      --file "$compose_overlay_secondary" \
      "$@"
  elif [ -n "$compose_overlay" ]; then
    docker compose \
      --project-name "$target_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$compose_overlay" \
      "$@"
  else
    docker compose \
      --project-name "$target_project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      "$@"
  fi
}

state_file="${LEONAID_RESTORE_STATE_FILE:-$env_file.restore-state.json}"
resume=${LEONAID_RESTORE_RESUME:-false}
compose config --format json >"$stage/compose.json"
restore_state() {
  action=$1
  shift
  python3 "$root/tools/backup/restore-state.py" "$action" \
    --state "$state_file" --config "$stage/compose.json" \
    --source "$source_project" --target "$target_project" --repository "$repository" \
    --expected-manifest "${LEONAID_RESTORE_EXPECTED_MANIFEST:-}" "$@"
}
if [ "$resume" = true ]; then
  restore_state check
else

if [ -n "$(docker ps -aq \
  --filter "label=com.docker.compose.project=$target_project")" ]; then
  fail "Restore-Ziel besitzt bereits Container"
fi
if [ -n "$(docker volume ls -q \
  --filter "label=com.docker.compose.project=$target_project")" ]; then
  fail "Restore-Ziel besitzt bereits Volumes"
fi

if [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$target_project")" ]; then
  fail "Restore-Ziel besitzt bereits Netzwerke"
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
        --user "$(id -u):$(id -g)" \
        -e RESTIC_CACHE_DIR=/tmp/restic-cache \
        -e RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
        -e RESTIC_REPOSITORY=/repository \
        --env-file "$credentials_file" \
        -v "$password_file:/run/secrets/restic-password:ro" \
        -v "$stage:/restore" \
        -v "$repository:/repository" \
        "$RESTIC_IMAGE" "$restic_command" "$@"
    else
      docker run --rm \
        --user "$(id -u):$(id -g)" \
        -e RESTIC_CACHE_DIR=/tmp/restic-cache \
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
  --env-file "$env_file" \
  -e PYTHONPATH=/workspace \
  -v "$root:/workspace:ro" \
  -v "$backup_root:/backup:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/backup/manifest.py /backup \
    --source-project "$source_project" --topology "$topology" --require-cms-key

if [ -n "${LEONAID_RESTORE_EXPECTED_MANIFEST:-}" ]; then
  cmp -s "$backup_root/manifest.json" "$LEONAID_RESTORE_EXPECTED_MANIFEST" ||
    fail "Restic-Backup entspricht nicht dem bestätigten Manifest"
fi

for volume in twenty-server-data rustfs-data; do
  docker volume create \
    --label "com.docker.compose.project=$target_project" \
    --label "com.docker.compose.volume=$volume" \
    "${target_project}_$volume" >/dev/null
done
if [ "$topology" = emdash ]; then
  docker volume create \
    --label "com.docker.compose.project=$target_project" \
    --label "com.docker.compose.volume=cms-bootstrap-state" \
    "${target_project}_cms-bootstrap-state" >/dev/null
  docker run --rm --network none \
    -v "${target_project}_cms-bootstrap-state:/target" \
    -v "$backup_root:/backup:ro" "$ALPINE_IMAGE" \
    tar -C /target -xf /backup/cms-bootstrap-state.tar
fi
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


compose up --detach --wait --wait-timeout 420 \
  core-postgres twenty-postgres rustfs
compose exec -T core-postgres pg_restore \
  --username "${CORE_POSTGRES_USER:-leonaid}" \
  --dbname "${CORE_POSTGRES_DB:-leonaid}" \
  --clean \
  --if-exists \
  --exit-on-error --single-transaction \
  --no-owner \
  --no-privileges \
  <"$backup_root/core.dump"
compose exec -T twenty-postgres pg_restore \
  --username "${TWENTY_POSTGRES_USER:-twenty}" \
  --dbname "${TWENTY_POSTGRES_DB:-default}" \
  --clean \
  --if-exists \
  --exit-on-error --single-transaction \
  --no-owner \
  --no-privileges \
  <"$backup_root/twenty.dump"

if [ "$topology" = emdash ]; then
  compose run --rm --no-deps cms-recovery-operator provision
  compose exec -T core-postgres pg_restore \
    --username "${CORE_POSTGRES_USER:-leonaid}" --dbname emdash --role emdash \
    --exit-on-error --single-transaction --no-owner --no-privileges \
    <"$backup_root/emdash.dump"
  compose run --rm --no-deps cms-recovery-operator verify
fi

restore_state prepare --manifest "$backup_root/manifest.json"
fi

# This also gates START_APP=false: callers must not receive a successful restore
# and then accidentally start resurrected survey data themselves.
. "$root/tools/backup/survey-erasure-gate.sh"
apply_survey_erasure_gate

restore_state verified

if [ "$topology" = emdash ]; then
  echo "restore: CMS SQL and closed bootstrap recovered; application remains stopped pending release verification"
  exit 0
fi

if [ "${LEONAID_RESTORE_START_APP:-true}" = "true" ]; then
  restore_state starting
  if [ "$restore_no_build" = "true" ]; then
    if [ "$restore_profile" = "none" ]; then
      compose up --no-build --pull missing \
        --detach --wait --wait-timeout 420
    else
      compose --profile "$restore_profile" up --no-build --pull missing \
        --detach --wait --wait-timeout 420
    fi
  elif [ "$restore_profile" = "none" ]; then
    compose up --build --detach --wait --wait-timeout 420
  else
    compose --profile "$restore_profile" up --build \
      --detach --wait --wait-timeout 420
  fi
fi

if [ "${LEONAID_RESTORE_START_APP:-true}" = "true" ]; then restore_state complete; fi

echo "restore: OK: $source_project wurde nach $target_project wiederhergestellt"
