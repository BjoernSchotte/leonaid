# Sourced by the isolated auth-runtime harness (mode emdash-upgrade) after the
# designated-operator setup. The stack runs the legacy CMS (EmDash 0.36.0 image
# and tools, see emdash-upgrade-legacy.sh). This phase imports the real
# Krapfentaxi campaign with the legacy release, upgrades the same database to
# the current release through the reviewed controller and proves the content,
# media, bindings and public pages afterwards. Core is never restarted.
snapshot() {
  compose run --rm --no-deps --user "$(id -u):$(id -g)" \
    --volume "$root:/repo:ro" --volume "$proof:/proof" \
    cms-db-operator node /repo/tools/emdash_spike/emdash-upgrade-snapshot.mjs "$@"
}
expect_upgrade_refusal() {
  if output=$("$@" 2>&1); then echo "emdash-upgrade: unexpected success" >&2; exit 1; else status=$?; fi
  if [ "$status" -ne 1 ]; then printf '%s\n' "$output" >&2; exit "$status"; fi
  case "$output" in *"cms-migration: refused; CMS traffic must remain closed"*) ;; *)
    printf '%s\n' "$output" >&2
    echo "emdash-upgrade: missing expected denial" >&2; exit 1 ;; esac
  unset output
}
controller() {
  /bin/sh "$root/tools/pilot_release/migrate-cms.sh" "$root" "$project" "$cms_image" "$1" \
    "$root/infra/compose/compose.yml" \
    "$root/infra/emdash-spike/identity.test.yml" \
    "$root/infra/emdash-spike/service.test.yml" \
    "$root/infra/emdash-spike/core-auth.test.yml" \
    "$root/infra/emdash-spike/auth-runtime.test.yml" \
    "$root/infra/emdash-spike/bootstrap.test.yml" \
    "$root/infra/emdash-spike/login.test.yml" \
    "$root/infra/emdash-spike/media-runtime.test.yml" \
    "$root/infra/emdash-spike/import-runtime.test.yml" \
    "$root/infra/emdash-spike/isolated-networks.test.yml"
}

# Legacy release: real import, published campaign and its public route.
fixture /repo/tools/emdash_spike/core_auth_fixture.py publication-open
compose run --rm --no-deps --volume "$proof:/proof:ro" krapfentaxi-import-probe
compose up --no-deps --build --detach --wait public mailpit worker
# The importer creates a draft; publish it with the legacy release so the
# upgrade starts from live content with draft and live revisions. The
# importer logged its operator session out, so use fresh Core sessions.
fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare /proof/emdash-upgrade-sessions.json
compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
  node tools/emdash_spike/emdash-upgrade-publish.mjs
snapshot capture legacy

# Close CMS traffic with the legacy operator, then replace the CMS container
# with the current image. The durable marker keeps the new process closed.
compose run --rm --no-deps --entrypoint node campaign-site \
  /app/operator/cms-migration-operator.mjs close
compose stop campaign-site
emdash_upgrade_legacy=false
compose build campaign-site
compose up --no-deps --no-start campaign-site
cms_image=$(docker image inspect --format '{{.Id}}' "$project-campaign-site")
legacy_image=$(docker image inspect --format '{{.Id}}' "$EMDASH_UPGRADE_LEGACY_IMAGE")
[ "$cms_image" != "$legacy_image" ]
[ "$(docker inspect --format '{{.Image}}' "$(compose ps --all --quiet campaign-site)")" = "$cms_image" ]
LEONAID_CMS_MIGRATION_IMAGE=$(/bin/sh "$root/tools/backup/verify-cms-image.sh" "$root" "$cms_image")
export LEONAID_CMS_MIGRATION_IMAGE

# The current release refuses the legacy schema until its own migrations ran.
expect_upgrade_refusal controller verify
snapshot compare-unchanged legacy
controller upgrade-emdash
snapshot capture upgraded
snapshot compare legacy upgraded
# Repeatable: a second run applies nothing and verifies the exact inventory.
controller upgrade-emdash
controller verify
snapshot compare-unchanged upgraded

# Reopening CMS traffic is an explicit operator action after verification.
compose run --rm --no-deps --entrypoint rmdir campaign-site \
  /app/bootstrap-state/cms-maintenance
compose up --no-deps --detach --wait campaign-site
compose run --rm --no-deps --volume "$proof:/proof:ro" bootstrap-probe \
  node tools/emdash_spike/emdash-upgrade-publish.mjs --public-only --unpublish
compose run --rm --no-deps admin-browser \
  node tools/emdash_spike/krapfentaxi-import-browser-proof.mjs
# Core aliases and redirects to the page published in the upgraded CMS.
fixture /repo/tools/emdash_spike/redirect_http_proof.py --published
echo "emdash-upgrade: real Krapfentaxi content imported with EmDash 0.36.0, upgraded in place to the pinned release under closed traffic, content/media/bindings kept, edited and published in three browsers; Core not restarted"
