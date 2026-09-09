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
compose run --rm --no-deps operator tools/emdash_spike/recovery-media-seed.mjs
compose run --rm --no-deps operator tools/backup/cms-recovery.mjs verify
compose exec -T core-postgres pg_dump -U leonaid -d emdash --format custom --no-owner --no-privileges >"$proof/emdash.dump"
compose run --rm --no-deps --env PGHOST=restore-postgres operator tools/backup/cms-recovery.mjs provision
restore_sql() {
  compose exec -T restore-postgres pg_restore -U leonaid -d emdash --role emdash \
    --exit-on-error --single-transaction --clean --if-exists --no-owner --no-privileges <"$proof/emdash.dump"
}
verify_target() {
  compose run --rm --no-deps --env PGHOST=restore-postgres operator tools/backup/cms-recovery.mjs verify-application
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
reject_schema_drift() {
  # Each mutation is confined to the dedicated restored fixture. Recovery uses
  # pg_restore, never an implicit repair in the validation operator.
  compose exec -T restore-postgres psql -U leonaid -d emdash -v ON_ERROR_STOP=1 -c "$1" >/dev/null
  if result=$(verify_target 2>&1); then
    echo "recovery-sql: application schema drift accepted" >&2
    exit 1
  else
    status=$?
    [ "$status" -eq 1 ] || exit "$status"
  fi
  case "$result" in *"cms-recovery: refused; CMS must remain stopped"*) ;; *) exit 1 ;; esac
  unset result
  # Prove the verifier did not silently repair the deliberately changed state.
  value=$(compose exec -T restore-postgres psql -U leonaid -d emdash -At -v ON_ERROR_STOP=1 -c "$2")
  [ "$value" = "$3" ] || { echo "recovery-sql: verification changed drifted state" >&2; exit 1; }
  restore_sql
  verify_target
  compose run --rm --no-deps operator tools/emdash_spike/recovery-sql-proof.mjs
}
reject_schema_drift \
  "UPDATE options SET value='999' WHERE name='leonaid:campaign_schema_version'" \
  "SELECT value FROM options WHERE name='leonaid:campaign_schema_version'" 999
reject_schema_drift \
  "UPDATE _emdash_fields SET label='Synthetic schema drift' WHERE slug='hero_summary'" \
  "SELECT label FROM _emdash_fields WHERE slug='hero_summary'" 'Synthetic schema drift'
reject_schema_drift \
  "UPDATE options SET value='999' WHERE name='leonaid:campaign_media_version'" \
  "SELECT value FROM options WHERE name='leonaid:campaign_media_version'" 999
reject_schema_drift \
  'ALTER TABLE public.leonaid_campaign_media DISABLE TRIGGER leonaid_campaign_media_guard' \
  "SELECT tgenabled FROM pg_trigger WHERE tgname='leonaid_campaign_media_guard'" D
expected_remaining=$(compose exec -T restore-postgres psql -U leonaid -d emdash -At -v ON_ERROR_STOP=1 \
  -c 'SELECT count(*)-1 FROM _emdash_migrations')
reject_schema_drift \
  'DELETE FROM _emdash_migrations WHERE name=(SELECT name FROM _emdash_migrations ORDER BY name LIMIT 1)' \
  'SELECT count(*) FROM _emdash_migrations' "$expected_remaining"
reject_schema_drift \
  "INSERT INTO _emdash_migrations (name,timestamp) SELECT 'synthetic_future_migration',timestamp FROM _emdash_migrations LIMIT 1" \
  "SELECT count(*) FROM _emdash_migrations WHERE name='synthetic_future_migration'" 1
echo "recovery-sql: exact application schema, media guard and missing/unknown upstream migration drift denied without repair; each fresh re-restore matches all source rows and sequences"
