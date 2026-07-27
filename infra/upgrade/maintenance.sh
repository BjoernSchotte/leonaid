#!/bin/sh
set -eu

root=${2:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

action=${1:-}
project=${LEONAID_COMPOSE_PROJECT:-leonaid}
compose_file="$root/infra/compose/compose.yml"
compose_overlay=${LEONAID_MAINTENANCE_COMPOSE_OVERLAY:-}
env_file="$root/.env.local"
state_volume="${project}_maintenance-state"

fail() {
  echo "maintenance: ERROR: $*" >&2
  exit 1
}

[ -f "$env_file" ] || fail ".env.local fehlt"
if [ -n "$compose_overlay" ]; then
  compose_overlay=$(cd "$(dirname "$compose_overlay")" && pwd)/$(basename "$compose_overlay")
  case "$compose_overlay" in
    "$root"/*) ;;
    *) fail "Maintenance-Compose-Overlay muss innerhalb des Repositories liegen" ;;
  esac
  [ -f "$compose_overlay" ] || fail "Maintenance-Compose-Overlay fehlt"
fi

compose() {
  if [ -n "$compose_overlay" ]; then
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

volume_exists() {
  docker volume inspect "$state_volume" >/dev/null 2>&1
}

case "$action" in
  enable)
    volume_exists || fail "Wartungsvolume fehlt; LeonAid muss zuerst laufen"
    docker run --rm \
      -v "$state_volume:/state" \
      "$ALPINE_IMAGE" \
      sh -eu -c 'printf "%s\n" "enabled" > /state/enabled'
    compose stop worker twenty-worker twenty-server >/dev/null
    echo "maintenance: OK: Schreibzugriffe blockiert; Worker und Twenty gestoppt"
    ;;
  disable)
    volume_exists || fail "Wartungsvolume fehlt"
    compose up --detach --wait --wait-timeout 420 \
      twenty-server twenty-worker worker >/dev/null
    docker run --rm \
      -v "$state_volume:/state" \
      "$ALPINE_IMAGE" \
      rm -f /state/enabled
    echo "maintenance: OK: Abhängigkeiten bereit; Schreibzugriffe wieder freigegeben"
    ;;
  status)
    if volume_exists && docker run --rm \
      -v "$state_volume:/state:ro" \
      "$ALPINE_IMAGE" \
      test -f /state/enabled; then
      echo "maintenance: enabled"
      exit 0
    fi
    echo "maintenance: disabled"
    exit 1
    ;;
  *)
    echo "Usage: infra/upgrade/maintenance.sh <enable|disable|status> [ROOT]" >&2
    exit 64
    ;;
esac
