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
- The **operator** promotes exactly this manifest to staging first, and to
  production only after green gates.
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

The promotion itself runs only through `upgrade`. The command verifies
manifest and doctor, writes the started event, creates a fresh encrypted
recovery point, activates maintenance mode, runs the explicit Twenty and
core migrations, starts without a build and lifts maintenance mode only after
a green final doctor run.
`--evidence-id` references the private, already completed functional
browser/document evidence for exactly this manifest SHA; the command itself
does not simulate human acceptance.

## 2. Staging

1. Deploy the approved manifest to staging for the first time with
   `pilot-deploy`.
2. Check the full golden journey, relevant documents and functional
   configuration; bind the private record firmly to the manifest SHA and
   evidence ID.
3. Then run the technical promotion of the same manifest:

```sh
./leonaid upgrade \
  --env-file /etc/leonaid/staging.env \
  --backup-manifest /var/lib/leonaid/evidence/staging-backup-manifest.json \
  --release-manifest /var/lib/leonaid/evidence/release-2026.1.0.json \
  --ledger /var/lib/leonaid/evidence/release-ledger.jsonl \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --evidence-id PILOT-RELEASE-STAGING-2026-01
```

The command enforces the order described above and records
`staging_started`, and `staging_verified` only after the green final doctor
run. The ledger holds only sequence, timestamp, release ID, manifest SHA,
event, result and external evidence ID.

## 3. Production

Before `production_started`, the ledger checks that **the same manifest SHA**
is already recorded as `staging_verified`. After that the same order as in
staging applies. A new manifest, even with seemingly identical images,
starts again at staging.

Before every write, record:

- maintenance window and operator;
- manifest SHA and approved commit;
- external, integrity-checked recovery point;
- private evidence ID of the approval.

Production builds no images and runs no unbound `head` migration. Target
revision, files and SHAs come from the already verified manifest.

```sh
./leonaid upgrade \
  --env-file /etc/leonaid/production.env \
  --backup-manifest /var/lib/leonaid/evidence/production-backup-manifest.json \
  --release-manifest /var/lib/leonaid/evidence/release-2026.1.0.json \
  --ledger /var/lib/leonaid/evidence/release-ledger.jsonl \
  --password-file /secure/leonaid/restic-password \
  --credentials-file /secure/leonaid/restic-backend.env \
  --evidence-id PILOT-RELEASE-PRODUCTION-2026-01
```

If the ledger lacks `staging_verified` for the same manifest SHA, the command
stops before the started event, backup, maintenance mode and deployment.

**Staging on another host** (for example a VM in the club's own network):
each host keeps its own ledger. Copy the staging ledger to the production
host and pass it with `--staging-ledger`:

```sh
scp staging-host:/var/lib/leonaid/evidence/release-ledger.jsonl \
  /var/lib/leonaid/evidence/staging-release-ledger.jsonl
./leonaid upgrade \
  --env-file /etc/leonaid/production.env \
  ... \
  --ledger /var/lib/leonaid/evidence/release-ledger.jsonl \
  --staging-ledger /var/lib/leonaid/evidence/staging-release-ledger.jsonl
```

The command only reads the copy and looks for `staging_verified` of the same
manifest SHA there; it writes production events to the production ledger
alone. Staging refuses `--staging-ledger`.

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

On a failure:

1. If maintenance mode was already requested, check its state and leave it
   active. A failure before the backup does not activate it; a failed final
   doctor run can occur after maintenance mode has already ended and is
   reported explicitly as such.
2. Record `production_failed` with a stable error class and the private
   evidence ID; do not copy logs or payloads into the public ledger.
3. Stop the faulty project. Do not correct data manually.
4. Record `rollback_started`.
5. Following the boundaries in
   [`../upgrade/README.md`](../upgrade/README.md), restore all affected
   stateful components together from the fresh recovery point into the
   explicitly confirmed target.
6. Start the source release with its unchanged manifest and `--no-build`.
7. Repeat the golden snapshot, document SHAs, readiness and browser journey.
8. Only on full success, deactivate maintenance mode and record
   `rollback_verified`.

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
restores, promotes the same manifest SHA again, also creates a cross-system
post-smoke failure and restores again. Both isolated Compose projects and
their volumes are removed afterwards. Sanitized local evidence is stored
under `.artifacts/pilot043/`.
