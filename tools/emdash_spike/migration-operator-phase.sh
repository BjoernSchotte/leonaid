# Sourced only by the isolated auth-runtime harness after real Core startup.
cms_id=$(compose ps --quiet campaign-site)
core_id=$(compose ps --quiet api)
image_id=$(docker inspect --format '{{.Image}}' "$cms_id")
LEONAID_CMS_MIGRATION_IMAGE=$(/bin/sh "$root/tools/backup/verify-cms-image.sh" "$root" "$image_id")
export LEONAID_CMS_MIGRATION_IMAGE
operator() { compose run --rm --no-deps cms-migration-operator "$@"; }
migration_fixture() { compose run --rm --no-deps cms-db-operator node tools/emdash_spike/migration-operator-fixture.mjs "$@"; }
expect_refusal() {
  if output=$("$@" 2>&1); then echo "cms-migration: unexpected success" >&2; exit 1; else status=$?; fi
  [ "$status" -eq 1 ] || exit "$status"
  case "$output" in *"cms-migration: refused; CMS traffic must remain closed"*) ;; *) echo "cms-migration: missing expected denial" >&2; exit 1 ;; esac
  unset output
}
controller() {
  /bin/sh "$root/tools/pilot_release/migrate-cms.sh" "$root" "$project" "$image_id" "$1" \
    "$root/infra/compose/compose.yml" \
    "$root/infra/emdash-spike/identity.test.yml" \
    "$root/infra/emdash-spike/service.test.yml" \
    "$root/infra/emdash-spike/core-auth.test.yml" \
    "$root/infra/emdash-spike/auth-runtime.test.yml" \
    "$root/infra/emdash-spike/bootstrap.test.yml" \
    "$root/infra/emdash-spike/login.test.yml"
}
traffic_probe() {
  # Direct runtime proof, independent of proxy access controls; no host ports.
  compose run --rm --no-deps bootstrap-probe node tools/emdash_spike/migration-traffic-proof.mjs
  core_probe
  [ "$(compose ps --quiet api)" = "$core_id" ]
  [ "$(docker inspect --format '{{.State.Running}}' "$core_id")" = true ]
}
core_probe() {
  compose run --rm --no-deps --volume "$proof:/proof:ro" core-auth-probe \
    bun tools/emdash_spike/core-auth-proof.mjs
}
core_probe
expect_refusal operator upgrade-v2
migration_fixture prepare
expect_refusal controller upgrade-v2
[ "$(docker inspect --format '{{.State.Running}}' "$cms_id")" = false ]
migration_fixture assert-v2
# Deliberate test restart is NOT activation: persistent marker must still deny.
compose start campaign-site
traffic_probe
compose stop campaign-site
migration_fixture clear-failure
lock_container=$(compose run --detach --no-deps cms-db-operator node tools/emdash_spike/migration-operator-fixture.mjs hold-lock)
attempt=0
until migration_fixture assert-lock >/dev/null 2>&1; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 20 ] || exit 1
done
core_probe
expect_refusal controller upgrade-v2
migration_fixture assert-v2
docker stop "$lock_container" >/dev/null
docker rm "$lock_container" >/dev/null
controller upgrade-v2
migration_fixture assert-v3
controller verify
controller upgrade-v2
migration_fixture assert-v3
[ "$(docker inspect --format '{{.State.Running}}' "$cms_id")" = false ]
compose start campaign-site
traffic_probe
compose stop campaign-site
echo "cms-migration: actual image-owned v2 upgrade, failed DDL rollback, exclusive lock denial, unchanged draft/published/revisions, repeatability and persistent traffic closure proved; Core not restarted"
