#!/bin/sh
set -eu
root=$1
. "$root/tools/testing/owned_teardown.sh"
proof_argument=
case ${2:-content} in
  content) proof_script=campaign-content-proof.mjs ;;
  schema) proof_script=schema-runtime-proof.mjs ;;
  schema-migration) proof_script=schema-migration-proof.mjs ;;
  schema-migration-v2) proof_script=schema-migration-proof.mjs; proof_argument=--from-v2 ;;
  media) proof_script=campaign-media-proof.mjs ;;
  public) proof_script=published-campaign-proof.mjs ;;
  pool) proof_script=postgres-pool-proof.mjs ;;
  *) echo "campaign-content: unsupported proof" >&2; exit 2 ;;
esac
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/emdash-spike/postgres.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "campaign-content: project collision; refusing" >&2
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
compose up --detach --wait core-postgres
if [ -n "$proof_argument" ]; then
  compose run --rm --no-deps proof node "tools/emdash_spike/$proof_script" "$proof_argument"
else
  compose run --rm --no-deps proof node "tools/emdash_spike/$proof_script"
fi
