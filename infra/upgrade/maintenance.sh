#!/bin/sh
set -eu

root=${2:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

action=${1:-}
project=${LEONAID_COMPOSE_PROJECT:-leonaid}
compose_file="$root/infra/compose/compose.yml"
compose_overlay=${LEONAID_MAINTENANCE_COMPOSE_OVERLAY:-}
compose_overlay_secondary=${LEONAID_MAINTENANCE_COMPOSE_OVERLAY_SECONDARY:-}
env_file=${LEONAID_ENV_FILE:-"$root/.env.local"}
no_build=${LEONAID_MAINTENANCE_NO_BUILD:-false}
state_volume="${project}_maintenance-state"

fail() {
  echo "maintenance: ERROR: $*" >&2
  exit 1
}

[ -f "$env_file" ] || fail ".env.local is missing"
if [ -n "$compose_overlay" ]; then
  compose_overlay=$(cd "$(dirname "$compose_overlay")" && pwd)/$(basename "$compose_overlay")
  case "$compose_overlay" in
    "$root"/*) ;;
    *) fail "Maintenance Compose overlay must be inside the repository" ;;
  esac
  [ -f "$compose_overlay" ] || fail "Maintenance Compose overlay is missing"
fi
if [ -n "$compose_overlay_secondary" ]; then
  [ -n "$compose_overlay" ] ||
    fail "Secondary maintenance overlay requires a primary overlay"
  compose_overlay_secondary=$(
    cd "$(dirname "$compose_overlay_secondary")" &&
      pwd
  )/$(basename "$compose_overlay_secondary")
  case "$compose_overlay_secondary" in
    "$root"/*) ;;
    *) fail "Secondary maintenance overlay must be inside the repository" ;;
  esac
  [ -f "$compose_overlay_secondary" ] ||
    fail "Secondary maintenance overlay is missing"
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

volume_exists() {
  docker volume inspect "$state_volume" >/dev/null 2>&1
}

case "$action" in
  enable)
    volume_exists || fail "Maintenance volume is missing; LeonAid must be running first"
    docker run --rm \
      -v "$state_volume:/state" \
      "$ALPINE_IMAGE" \
      sh -eu -c 'printf "%s\n" "enabled" > /state/enabled'
    compose stop worker twenty-worker twenty-server >/dev/null
    echo "maintenance: OK: writes blocked; worker and Twenty stopped"
    ;;
  disable)
    volume_exists || fail "Maintenance volume is missing"
    if [ "$no_build" = "true" ]; then
      compose up --detach --no-build --pull missing --wait --wait-timeout 420 \
        twenty-server twenty-worker worker >/dev/null
    else
      compose up --detach --wait --wait-timeout 420 \
        twenty-server twenty-worker worker >/dev/null
    fi
    docker run --rm \
      -v "$state_volume:/state" \
      "$ALPINE_IMAGE" \
      rm -f /state/enabled
    echo "maintenance: OK: dependencies ready; writes enabled again"
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
