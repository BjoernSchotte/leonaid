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
recovery_overlay_list=${LEONAID_BACKUP_COMPOSE_OVERLAY_LIST:-}
env_file=${LEONAID_ENV_FILE:-"$root/.env.local"}
topology=${LEONAID_BACKUP_TOPOLOGY:-legacy}
case "$topology" in legacy|emdash) ;; *) echo "backup: ERROR: unknown topology" >&2; exit 1 ;; esac
manifest_output=${LEONAID_BACKUP_MANIFEST_OUTPUT:-}
manifest_output_tmp=
stage=$(mktemp -d)
writers_stopped=false
restart_services=""

fail() {
  echo "backup: ERROR: $*" >&2
  exit 1
}
. "$root/tools/backup/compose-overlays.sh"
validate_recovery_overlays

[ -f "$env_file" ] || fail "environment file missing"
[ -n "$repository" ] || fail "LEONAID_BACKUP_REPOSITORY missing"
[ -n "$password_file" ] || fail "LEONAID_BACKUP_PASSWORD_FILE missing"
if [ -n "$compose_overlay" ]; then
  compose_overlay=$(cd "$(dirname "$compose_overlay")" && pwd)/$(basename "$compose_overlay")
  case "$compose_overlay" in
    "$root"/*) ;;
    *) fail "backup Compose overlay must be inside the repository" ;;
  esac
  [ -f "$compose_overlay" ] || fail "backup Compose overlay missing"
fi
if [ -n "$compose_overlay_secondary" ]; then
  [ -n "$compose_overlay" ] ||
    fail "secondary backup Compose overlay requires a primary overlay"
  compose_overlay_secondary=$(
    cd "$(dirname "$compose_overlay_secondary")" &&
      pwd
  )/$(basename "$compose_overlay_secondary")
  case "$compose_overlay_secondary" in
    "$root"/*) ;;
    *) fail "secondary backup Compose overlay must be inside the repository" ;;
  esac
  [ -f "$compose_overlay_secondary" ] ||
    fail "secondary backup Compose overlay missing"
fi
if [ -n "$manifest_output" ]; then
  case "$manifest_output" in
    /*) ;;
    *) fail "backup manifest output must be an absolute path" ;;
  esac
  [ -d "$(dirname "$manifest_output")" ] ||
    fail "directory for backup manifest output missing"
  manifest_output_tmp="$manifest_output.tmp.$$"
fi

compose() {
  if [ -n "$recovery_overlay_list" ]; then
    # Preserve list order by placing accumulated file arguments after the base.
    # Each invocation revalidates before Docker can act.
    validate_recovery_overlays
    overlay_arguments=""
    while IFS= read -r relative || [ -n "$relative" ]; do
      overlay_arguments="$overlay_arguments --file $relative"
    done < "$recovery_overlay_list"
    # Paths contain no whitespace/metacharacters after validation. Resolve
    # relative paths from root so roots containing spaces remain supported.
    (cd "$root" && docker compose --project-name "$project" --env-file "$env_file" \
      --file "$compose_file" $overlay_arguments --profile emdash "$@")
    return
  fi
  set -- --profile emdash "$@"
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
    echo "backup: resuming previously running services; waiting for readiness"
    # `compose start --wait` exists only since Compose v5; v2 (GitHub runners,
    # many hosts) rejects the flag before starting anything. `up` restarts the
    # stopped containers as they are and waits for their health on both.
    if ! compose up --detach --no-deps --no-recreate --no-build --pull never \
      --wait --wait-timeout 420 $restart_services >/dev/null 2>&1; then
      echo "backup: ERROR: source services failed to resume; inspect service health before continuing" >&2
      if [ "$status" -eq 0 ]; then status=1; fi
    fi
  fi
  if [ -n "$manifest_output_tmp" ]; then
    rm -f "$manifest_output_tmp"
  fi
  rm -rf "$stage"
  if [ "$status" -eq 0 ]; then
    echo "backup: OK: $project consistent, encrypted and integrity-checked; source services resumed"
  fi
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
      [ -f "$credentials_file" ] || fail "backup credentials file missing"
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
      [ -f "$credentials_file" ] || fail "backup credentials file missing"
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
    fail "service is not ready: $required"
done
cms_database=$(compose exec -T core-postgres psql \
  --username "${CORE_POSTGRES_USER:-leonaid}" \
  --dbname "${CORE_POSTGRES_DB:-leonaid}" -Atc \
  "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname='emdash')")
case "$topology:$cms_database" in
  legacy:f|emdash:t) ;;
  legacy:t)
    # A CMS that never completed its editor setup (provisioning under way,
    # or switched off again before it went live) holds no editorial data and
    # cannot be restored anyway (cms_state.py); a live CMS must be backed up.
    if docker volume inspect "${project}_cms-bootstrap-state" >/dev/null 2>&1 &&
      docker run --rm --network none \
        -v "${project}_cms-bootstrap-state:/state:ro" "$ALPINE_IMAGE" \
        cat /state/state.json 2>/dev/null | grep -Fq '"status":"complete"'; then
      fail "the CMS is live; back it up with the CMS topology (LEONAID_CMS_ENABLED=true)"
    fi
    echo "backup: the unfinished CMS (setup not complete) is not part of this backup"
    ;;
  *) fail "backup topology does not match the existing CMS data" ;;
esac
if [ "$topology" = emdash ]; then
  bootstrap_project=$(docker volume inspect --format '{{ index .Labels "com.docker.compose.project" }}' "${project}_cms-bootstrap-state")
  [ "$bootstrap_project" = "$project" ] || fail "CMS bootstrap volume missing or belongs to another project"
fi
for service in twenty-server twenty-worker api worker public pwa web proxy campaign-site rustfs; do
  if echo "$running" | grep -Fx "$service" >/dev/null; then
    restart_services="$restart_services $service"
  fi
done

writers_stopped=true
compose stop \
  proxy api worker public pwa web twenty-worker twenty-server campaign-site \
  >/dev/null

if [ "$topology" = emdash ]; then
  compose exec -T core-postgres pg_dump \
    --username "${CORE_POSTGRES_USER:-leonaid}" --dbname emdash \
    --format custom --no-owner --no-privileges >"$stage/emdash.dump"
  # Root reads the volume; the host shell writes the archive as the operator.
  docker run --rm --network none \
    -v "${project}_cms-bootstrap-state:/source:ro" "$ALPINE_IMAGE" \
    tar -C /source -cf - . >"$stage/cms-bootstrap-state.tar"
fi

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

# Archive the object store only after it has stopped flushing its on-disk state.
# Application writers are already stopped; cleanup restarts only services that
# were running before this backup, including RustFS.
compose stop rustfs >/dev/null

# Root reads the volumes; the host shell writes the archives as the operator,
# so the stage never holds root-owned files.
docker run --rm --network none \
  -v "${project}_twenty-server-data:/source:ro" \
  "$ALPINE_IMAGE" \
  tar -C /source -cf - . >"$stage/twenty-storage.tar"
docker run --rm --network none \
  -v "${project}_rustfs-data:/source:ro" \
  "$ALPINE_IMAGE" \
  tar -C /source -cf - . >"$stage/rustfs-data.tar"
# Certificates and the ACME account of every host (pilot proxy only; the dev
# proxy keeps no data volume). The proxy is stopped above.
if docker volume inspect "${project}_caddy-data" >/dev/null 2>&1; then
  docker run --rm --network none \
    -v "${project}_caddy-data:/source:ro" \
    "$ALPINE_IMAGE" \
    tar -C /source -cf - . >"$stage/caddy-data.tar"
fi

# As the host user: the manifest is created 0600, and the host copies it to
# LEONAID_BACKUP_MANIFEST_OUTPUT below. A root-owned file would be unreadable
# on native Linux (Docker Desktop hides this).
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  --env-file "$env_file" \
  -e PYTHONPATH=/workspace \
  -v "$root:/workspace:ro" -v "$stage:/backup" "$PYTHON_IMAGE" \
  python /workspace/tools/backup/manifest.py /backup \
  --source-project "$project" --topology "$topology" --create

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

echo "backup: snapshot integrity verified; completing source recovery"
