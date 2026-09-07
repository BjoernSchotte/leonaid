#!/bin/sh
set -eu
root=$1
proof=$(mktemp -d)
suffix=$(basename "$proof" | tr '[:upper:].' '[:lower:]-')
project="leonaid-emdash-$suffix"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/emdash-spike/recovery-sql.test.yml" "$@"
}
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || \
   [ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$project")" ]; then
  rmdir "$proof"
  echo "recovery-sql: project collision; refusing" >&2
  exit 1
fi
cleanup() {
  compose down --volumes >/dev/null
  rm -f "$proof/emdash.dump"
  rmdir "$proof"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
compose up --detach --wait core-postgres restore-postgres
compose run --rm --no-deps operator tools/emdash_spike/service-provision.mjs
compose run --rm --no-deps operator tools/emdash_spike/campaign-runtime-seed.mjs
compose run --rm --no-deps operator tools/backup/cms-recovery.mjs verify
compose exec -T core-postgres pg_dump -U leonaid -d emdash --format custom --no-owner --no-privileges >"$proof/emdash.dump"
compose run --rm --no-deps --env PGHOST=restore-postgres operator tools/backup/cms-recovery.mjs provision
restore_sql() {
  compose exec -T restore-postgres pg_restore -U leonaid -d emdash --role emdash \
    --exit-on-error --single-transaction --clean --if-exists --no-owner --no-privileges <"$proof/emdash.dump"
}
verify_target() {
  compose run --rm --no-deps --env PGHOST=restore-postgres operator tools/backup/cms-recovery.mjs verify
}
restore_sql
verify_target
compose run --rm --no-deps operator tools/emdash_spike/recovery-sql-proof.mjs
compose exec -T restore-postgres psql -U leonaid -d emdash -v ON_ERROR_STOP=1 \
  -c 'ALTER TABLE public.ec_campaign_pages DISABLE TRIGGER leonaid_campaign_binding' >/dev/null
if verify_target; then echo "recovery-sql: disabled guard accepted" >&2; exit 1; fi
restore_sql
verify_target
compose exec -T restore-postgres psql -U leonaid -d emdash -v ON_ERROR_STOP=1 \
  -c 'DROP TRIGGER leonaid_campaign_binding ON public.ec_campaign_pages' >/dev/null
if verify_target; then echo "recovery-sql: missing guard accepted" >&2; exit 1; fi
restore_sql
verify_target
compose run --rm --no-deps operator tools/emdash_spike/recovery-sql-proof.mjs
echo "recovery-sql: actual separate-database dump/restore, guard denial and restore-based recovery passed; no HTTP or media claim"
