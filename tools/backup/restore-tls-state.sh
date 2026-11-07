# Sourced by tools/backup/restore-body.sh and tools/backup/test.sh.
#
# restore_tls_state BACKUP_ROOT TARGET_PROJECT
#
# caddy-data.tar holds the TLS private keys and the ACME account of the
# production hosts. Only an explicit restore of the installation itself (new
# server, same host names) takes it: LEONAID_RESTORE_TLS_STATE=true
# (pilot-restore --with-tls-state). A plain restore, staging and drill targets
# create no caddy-data volume and request their own certificates.
# Needs ALPINE_IMAGE (infra/locks/images.env).
restore_tls_state() {
  tls_backup_root=$1
  tls_target_project=$2
  tls_wanted=${LEONAID_RESTORE_TLS_STATE:-false}
  case "$tls_wanted" in
    true | false) ;;
    *)
      echo "restore: ERROR: LEONAID_RESTORE_TLS_STATE must be true or false" >&2
      return 1
      ;;
  esac
  [ -f "$tls_backup_root/caddy-data.tar" ] || return 0
  if [ "$tls_wanted" = false ]; then
    echo "restore: TLS certificates of the source not restored (no --with-tls-state)"
    return 0
  fi
  docker volume create \
    --label "com.docker.compose.project=$tls_target_project" \
    --label "com.docker.compose.volume=caddy-data" \
    "${tls_target_project}_caddy-data" >/dev/null || return 1
  docker run --rm --network none \
    -v "${tls_target_project}_caddy-data:/target" \
    -v "$tls_backup_root:/backup:ro" "$ALPINE_IMAGE" \
    tar -C /target -xf /backup/caddy-data.tar
}
