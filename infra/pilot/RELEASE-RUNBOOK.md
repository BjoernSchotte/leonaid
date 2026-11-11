# Pilot release, migration and rollback

This runbook is the binding operations path for a LeonAid release.
It connects the hardened pilot topology, the deployment doctor, the
encrypted recovery point, maintenance mode and the existing
core/Twenty/RustFS migrations. It replaces neither a functional approval nor
any of the decisions due in `specs/leonaid-pilot/DECISIONS.md`.

## Roles and hard limits

- The **release owner** starts a CalVer release with `./leonaid release`.
  The `Release` workflow builds and publishes the six LeonAid images (core,
  web, PWA, public, proxy and survey validator) with tag and digest and
  attaches `release-images.env` and `release-manifest.json` to the GitHub
  release (see `apps/docs/.../ops/how-to/release-a-version.md`).
- The **operator** upgrades an installation to exactly this manifest, with
  an optional rehearsal on staging first.
- The **functional approver** confirms the golden journey, invoice content
  and relevant configuration; they do not work directly in the database.
- On the target system only `pull`, `up --no-build`, documented migrations,
  smoke tests and, if needed, restore run. A build, a live-code mount or
  ad-hoc resolution of new dependencies is forbidden.
- A failed migration, readiness or functional smoke test does not lift
  maintenance mode.

## 1. Create the manifest from the effective configuration

The approved commit, the private `0600` environment file and all published
images with tag **and** digest must already be fixed. First, write the
effective Compose configuration:

```sh
docker compose \
  --project-name leonaid-staging-club-111 \
  --env-file /etc/leonaid/staging.env \
  --file infra/compose/compose.yml \
  --file infra/pilot/compose.yml \
  config --format json >.local/pilot/evidence/staging-compose.json
```

The manifest takes over the twelve service images actually in use and also
binds:

- the full Git commit and release ID;
- all Alembic revisions with SHA-256 and the expected head;
- OpenAPI, the compatibility matrix and the Typst invoice template with SHA-256;
- golden dataset and template version;
- required gates and the rollback boundary per stateful component.

```sh
./leonaid pilot-release-manifest create \
  --release-id pilot-2026-01 \
  --version 2026.1.0 \
  --git-commit "$(git rev-parse HEAD)" \
  --deployment-mode production \
  --compose-config .local/pilot/evidence/staging-compose.json \
  --output .local/pilot/evidence/release-2026.1.0.json

./leonaid pilot-release-manifest verify \
  --manifest .local/pilot/evidence/release-2026.1.0.json \
  --expected-commit "$(git rev-parse HEAD)" \
  --compose-config .local/pilot/evidence/staging-compose.json
```

`production` accepts no local image, no floating tag and no digest without a
tag. A diverging migration, a changed template or a difference between
manifest and Compose blocks before the first write.
`pilot-deploy` is the technical, manifest-bound start/reconcile without
migration. It can be used for the first staging setup and the functional
pre-acceptance:

```sh
./leonaid pilot-deploy \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --release-manifest .local/pilot/evidence/release-2026.1.0.json
```

`pilot-deploy` checks the due decisions before the start, uses no `build`,
waits for the real health state and then runs the full doctor against the
running environment.

The upgrade of a running installation runs only through `upgrade`:

1. **Pre-check, nothing changes yet.** The command verifies the manifest
   against the checkout and Compose and runs the doctor. Then the release's
   Core image reads the installed schema. If it does not know that schema,
   the release is older than the installation or a release in between must
   be installed first; the command stops.
2. **Backup.** It creates a fresh encrypted recovery point and keeps a copy
   of its manifest next to the configured one
   (`latest-backup-manifest.pre-upgrade-<time>.json`). Later nightly backups
   rewrite the configured manifest, never this copy. A failed backup stops
   the upgrade.
3. **Change.** It enables maintenance mode, runs the explicit RustFS, Twenty,
   Core and CMS migrations, starts without a build, applies the Twenty schema
   (with `--twenty-bootstrap-file`) and lifts maintenance mode. A final doctor
   run checks the installation.

```sh
./leonaid upgrade \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/latest-backup-manifest.json \
  --release-manifest /var/lib/leonaid/evidence/release-2026.1.0.json \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env
```

Production builds no images and runs no unbound `head` migration. Target
revision, files and SHAs come from the verified manifest.

## 2. Staging (optional)

Staging is a rehearsal, not a gate: production does not ask for it. A staging
installation may run on another host, for example a VM in the club's own
network, and waits for no decision in `DECISIONS.md`.

1. Restore the latest production backup into the staging project with
   `./leonaid pilot-restore` (staging has its own domains, bucket, SMTP and
   secrets; see [`README.md`](README.md)).
2. Run the same `upgrade` there with the new release manifest.
3. Check the golden journey, documents and campaign pages.
4. Then run `upgrade` on production.

## 3. CMS and monitoring

With `LEONAID_CMS_ENABLED=true` the release manifest is the CMS manifest
(`release-manifest-cms.json`), and `upgrade` also migrates the CMS, in
maintenance mode after Core and before the deploy. It closes CMS traffic as
soon as maintenance starts, so editors (who write without Core) cannot change
anything after the recovery point; from the backup to that moment the window
of release spec R8 applies. Its recovery point (taken
before maintenance) holds the CMS database, setup state and media. The
command recreates `campaign-site` on the release image without starting it,
and `tools/pilot_release/migrate-cms.sh` verifies that image against the
checkout, closes CMS traffic and runs `upgrade-emdash` when the image brings
EmDash migrations, else `verify`. CMS traffic reopens only after the migrated
state verifies; the deploy then starts the CMS. `pilot-deploy` refuses a
release with pending CMS migrations and points to `upgrade`.

`upgrade` and `pilot-deploy` leave the monitoring profile unchanged.
After every successful release,
`./leonaid pilot-monitoring --env-file /etc/leonaid/production.env` starts
the exporters, Prometheus and Alertmanager with the new release image; the
watchdog heartbeat keeps running meanwhile.

## 4. Failure and rollback

On a failure the command says where it stopped:

- **Before maintenance mode** (pre-check or backup): nothing changed, the
  installation keeps running. Fix the cause and run `upgrade` again.
- **After the backup**: maintenance mode stays on, so nobody changes data.
  The command prints the kept manifest copy and the complete
  `./leonaid pilot-restore` command for it.
- **The final doctor run** after maintenance mode ended: reported as such;
  users may already have written again.

Then either fix the cause and run the same `upgrade` again (every step is
repeatable; see the CMS notes below), or go back:

1. Stop the faulty project. Do not correct data manually.
2. Following the boundaries in
   [`../upgrade/README.md`](../upgrade/README.md), restore all stateful
   components together from the kept recovery point into an explicitly
   confirmed `leonaid-restore-*` project, with the printed `pilot-restore`
   command.
3. Start the previous release there with its unchanged manifest and
   `pilot-deploy` (no build).
4. Check readiness, the golden journey and documents, then switch the
   domains to the restored project.

An operator needs no SQL access for this. Direct database work counts as a
failed operations proof.

CMS: when the CMS step of `upgrade` fails, CMS traffic stays closed and
`campaign-site` stays stopped; Core and the rest of the release are not
touched further (the deploy does not run). The proof shows that a failing
EmDash migration rolls back completely (one transaction), so the database
keeps the previous state.

1. **Retry forward first** when the cause is transient or fixed (a pull or
   network error, a timeout, a corrected release image): lift maintenance as
   after any failed release and run `upgrade` again. It accepts the
   closed CMS when no `<project>-cms-migration-lock` container exists, and
   reopens traffic only after the migrated state verifies. A failure before
   the CMS step (backup, maintenance, Core migration) changed no CMS data:
   rerun as well.
2. **Restore** when the rerun fails again or the database was changed
   partly. Never start the previous CMS image against a partly or fully
   migrated CMS database; `pilot-deploy` with the previous manifest refuses
   the closed CMS. Roll back with steps 3 to 8:
restore the recovery point of this release (it contains the CMS database,
its setup state, the media and, through the release manifest, the CMS image)
into a fresh `leonaid-restore-*` project, start it with the previous release
manifest, check the campaign pages and switch over. Orders and edits made
after the recovery point are lost (release spec R8).

## Reproducible technical proof

```sh
./leonaid test-pilot-release
```

The test uses no mocks. It runs release v1 and v2 with real core
PostgreSQL, Twenty, RustFS, Restic, Typst PDFs and Chromium. It creates a
real missing Alembic revision, proves that the write lock stays in place,
restores, upgrades to the same manifest again, also creates a cross-system
post-smoke failure and restores again. Both isolated Compose projects and
their volumes are removed afterwards. Sanitized local evidence is stored
under `.artifacts/pilot043/`.
