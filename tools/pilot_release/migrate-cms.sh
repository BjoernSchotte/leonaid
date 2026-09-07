#!/bin/sh
set -eu
set -f
root=$1
root=$(cd "$root" && pwd -P)
project=$2
reference=$3
mode=$4
shift 4
fail() { echo "cms-migration-controller: refused; do not reopen CMS traffic" >&2; exit 1; }
case "$project" in ''|*[!a-z0-9_-]*) fail ;; esac
case "$mode" in verify|upgrade-v1|upgrade-v2) ;; *) fail ;; esac
[ "$#" -gt 0 ] || fail
# Explicit ordered Compose files, confined to this checkout. Never infer a
# project from the working directory or mutate another project's deployment.
for file in "$@"; do
  case "$file" in "$root"/infra/*) ;; *) fail ;; esac
  case "$file" in *[[:space:]]*) fail ;; esac
  [ -f "$file" ] && [ ! -L "$file" ] || fail
  parent=$(cd "$(dirname "$file")" && pwd -P)
  case "$parent" in "$root"/infra/*|"$root"/infra) ;; *) fail ;; esac
done
LEONAID_CMS_MIGRATION_IMAGE=$(/bin/sh "$root/tools/backup/verify-cms-image.sh" "$root" "$reference")
export LEONAID_CMS_MIGRATION_IMAGE
# Docker atomically acquires this project-scoped controller lock. A killed
# controller leaves a visible stopped lock container for operator inspection;
# no timeout, stale-lock stealing or implicit restart of CMS is permitted.
lock_id=$(docker create --name "$project-cms-migration-lock" --network none \
  --label "leonaid.cms-migration.project=$project" --entrypoint node \
  "$LEONAID_CMS_MIGRATION_IMAGE" -e 'process.exit(0)' 2>/dev/null) || fail
cleanup() { docker rm "$lock_id" >/dev/null; }
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
compose() {
  set -- --profile emdash "$@"
  set -- --file "$root/infra/emdash-spike/migration-operator.yml" "$@"
  # Paths containing whitespace are refused below; no eval or shell expansion
  # of user-supplied Compose contents occurs here.
  for file in $compose_files; do
    set -- --file "$file" "$@"
  done
  docker compose --project-name "$project" --env-file "${LEONAID_ENV_FILE:-$root/.env.local}" "$@"
}
# Reverse the validated list once because compose() prepends each file.
compose_files=
for file in "$@"; do
  compose_files="$file $compose_files"
done
cms_id=$(compose ps --all --quiet campaign-site)
case "$cms_id" in ''|*'
'*) fail ;; esac
[ "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$cms_id")" = "$project" ] || fail
[ "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$cms_id")" = campaign-site ] || fail
# This reviewed controller migrates local v1/v2 SQL under the already selected
# current image. Refuse an older/unreviewed runtime which may not implement the
# persistent traffic gate; binary successor upgrades need their own gate proof.
[ "$(docker inspect --format '{{.Image}}' "$cms_id")" = "$LEONAID_CMS_MIGRATION_IMAGE" ] || fail
compose run --rm --no-deps cms-migration-operator close
# Stop only CMS; terminate in-flight requests before any DDL. The persistent
# marker also denies traffic if an independent operator restarts the process.
compose stop campaign-site
[ "$(docker inspect --format '{{.State.Running}}' "$cms_id")" = false ] || fail
compose run --rm --no-deps cms-migration-operator "$mode"
echo "cms-migration-controller: passed; CMS remains stopped and traffic closed; Core untouched"
