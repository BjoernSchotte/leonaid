#!/bin/sh
set -eu
root=$1
. "$root/tools/testing/owned_teardown.sh"
mode=${2:-namespaces}
case "$mode" in namespaces|persistence|commands|renderer) ;; *) exit 2 ;; esac
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/emdash-spike/alias-namespaces.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "alias-namespaces: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose --profile '*' down --volumes --remove-orphans >/dev/null || leak_detected=1
  verify_owned_project_removed "$project" || leak_detected=1
  rmdir "$proof"
}
# A teardown leak fails the run even when the test itself passed.
trap 'cleanup; [ "${leak_detected:-0}" -eq 0 ] || exit 1' EXIT
trap 'exit 130' HUP INT TERM
compose build proof
compose up --detach --wait core-postgres
compose run --rm --no-deps --entrypoint python proof "tools/emdash_spike/alias_${mode}_proof.py"
