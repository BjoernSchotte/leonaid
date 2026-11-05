# Release updates — updating a club installation safely

Status: 2026-11-03. Specification for review. Nothing in this document is
implemented. Implementation needs a separate go per part (§13).

## 1. Context and terms

LeonAid is installed once per club on one 8 GB VPS (Docker Compose, Docker-only
CLI `./leonaid`). Two things must never be mixed up:

| Term             | What it is                                                                                                                                                                                                                         | Who owns it  |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| **Release**      | The generic open-source release `vYYYY.M.N[.P]`, identical for every installation: images with digests, schema migrations, shipped defaults, upgrade steps, notes. It knows nothing about any club.                              | the project  |
| **Installation** | One club's deployment: env file and secrets, and **all** data — actions, orders, invoices, members, the club's own templates and settings, legal texts, CMS pages and images, CRM data, files, survey answers, domains, certificates. | the club     |

An **update** moves one installation from release A to release B. Rule zero of
this spec: **an update changes the release, never the installation's content.**
Anything a club created or changed is still there, unchanged, after the update.
Where a release must change data shape, it may only add (new columns, new
shipped options) or perform a documented, reversible, behaviour-preserving
backfill (§6.4).

Terms used below:

- **Shipped default**: a row a release inserts so a fresh installation works
  (built-in action templates, feature flags, singletons).
- **Club-owned row**: any row a person in the club created or changed through
  the product, including a shipped default after the club edited it.
- **Upstream manifest**: the release manifest published by the Release
  workflow, the same bytes for every club.
- **Installation state**: a small local file that says which release runs
  here, from which manifest SHA, since when, and with which recovery point.

## 2. What exists today

All paths relative to the repository root.

### 2.1 Publishing a release

- `./leonaid release [--dry-run]` (`tools/release/release.sh`,
  `tools/release/release-lib.sh`) tags the next CalVer version after checking a
  clean tree, `HEAD == origin/main`, green CI and a `gh` login
  (`apps/docs/src/content/docs/en/ops/how-to/release-a-version.md`).
- `.github/workflows/release.yml` builds the six LeonAid images (core, web,
  pwa, public, proxy, survey-validator) with
  `tools/release/docker-bake.hcl` (provenance and SBOM attestations), refuses
  to overwrite an existing version, writes `release-images.env`
  (`tools/release/release_assets.py`), renders `infra/pilot/production.env.example`
  with these images, runs `docker compose config` and creates
  `release-manifest.json` with `tools/pilot_release/manifest.py create`
  (schema version 1). It attaches both files and `SHA256SUMS` to the GitHub
  release. **Nothing is signed**; `SHA256SUMS` comes from the same place as the
  files it hashes.
- The manifest (`tools/pilot_release/manifest.py`) binds: git commit, the
  thirteen service images with tag and digest, every Alembic migration with
  revision and SHA-256, the core head, golden data version 1, the
  `invoice-v2` Typst template, the OpenAPI document and
  `infra/upgrade/compatibility-matrix.json` with SHA-256, the required gates
  and the rollback boundary per stateful component. Schema version 2 adds the
  `campaign-site` image and a CMS identity (`tools/pilot_release/cms_identity.py`:
  EmDash package version and integrity, editorial schema version,
  `migrationMode: operator-only`, SHA-256 of 25 CMS source files, three CMS
  gates, rollback `restore_matching_cms_sql_media_key_image_preserve_later_core_orders`).
  The Release workflow still publishes schema version 1, so **the published
  manifest does not cover the CMS**.

### 2.2 Installing and updating a pilot installation

- Install: `apps/docs/src/content/docs/en/ops/how-to/install-on-a-vps.md`
  downloads `release-images.env` and `release-manifest.json` with `curl`,
  clones the repository to `/opt/leonaid` and checks out the release commit.
  `./leonaid pilot-install` then provisions an empty project.
- `infra/pilot/RELEASE-RUNBOOK.md` §1 still tells the operator to **create a
  second, per-installation manifest** from the effective Compose configuration
  of the staging env file (`pilot-release-manifest create --release-id pilot-2026-01 …`).
  The images in it are the ones copied from `release-images.env`, so it
  repeats the upstream manifest with a different `releaseId` and therefore a
  different SHA.
- `./leonaid pilot-deploy` verifies the manifest against the checkout
  (`git rev-parse HEAD`, migration files and artifact SHAs read from the
  checkout) and the effective Compose images, then `up --no-build`, waits and
  runs the full doctor.
- `./leonaid pilot-release` (`leonaid`, function `pilot_release`): verify
  manifest → doctor (`--gate pilot-release`) → ledger `*_started` → fresh
  encrypted backup (`pilot-backup`) → `infra/upgrade/maintenance.sh enable` →
  `pilot_release_migrate` (Valkey queue-store migration
  `infra/upgrade/twenty-queue-store.sh`, RustFS recreate, Twenty start/stop,
  `yarn command:prod upgrade`, `alembic upgrade <manifest head>`, head check) →
  `pilot-deploy` → optional `tools/twenty/provision.py apply` and CRM match
  key repair (only with `--twenty-bootstrap-file`) → maintenance disable →
  final doctor → ledger `*_verified`. Failure keeps maintenance on and records
  `production_failed`.
- The release ledger (`tools/pilot_release/promotion.py`) is an append-only,
  PII-free JSONL file. Production needs a `staging_verified` event for the
  **same manifest SHA**. `pilot-release` derives the stage from the project
  name (`leonaid-staging*` / `leonaid-production*`). Staging is a second,
  complete installation with its own domain, secrets, buckets and Restic
  repository (`infra/pilot/README.md`).
- Rollback is restore-only everywhere: `infra/upgrade/README.md` ("After
  `alembic upgrade head`, no older core is claimed to work against the new
  schema"), `infra/pilot/RELEASE-RUNBOOK.md` §4,
  `apps/docs/src/content/docs/en/ops/how-to/upgrade-and-rollback.md`.
- Third-party upgrades are tracked as single hops in
  `infra/upgrade/compatibility-matrix.json` (Twenty 2.24 → 2.54, RustFS
  beta.11 → 1.0.4, PostgreSQL, Valkey) with reviewed notes, expected data
  change and rollback boundary.

### 2.3 Backup and restore

- `./leonaid backup` / `pilot-backup` (`tools/backup/backup.sh`): short write
  stop, custom-format dumps of core and Twenty PostgreSQL, tar of Twenty files
  and the **whole RustFS volume** (generated invoices, documents, CMS media
  bucket `emdash-media`), manifest with SHA-256, Restic encryption, rotation,
  `restic check --read-data`.
- With `LEONAID_BACKUP_TOPOLOGY=emdash` it also dumps the `emdash` database and
  archives the `cms-bootstrap-state` volume; the restore requires the CMS
  encryption key (`--require-cms-key`, `tools/backup/restore-body.sh`) and can
  restore the CMS alone (`restore_scope=cms`). The default topology is
  `legacy`, and backup **fails closed** when the topology does not match the
  existence of the `emdash` database. `pilot-backup` never sets the topology,
  so the day the CMS runs in the pilot, `pilot-backup` refuses to run until it
  is wired up — safe, but it blocks every update.
- Not backed up: Valkey (rebuildable), Caddy data (certificates are
  re-issued; note that `specs/multi-domain/PLAN.md` §10.1 says the Caddy data
  volume is "in backups", which is not true today), the env file and secrets
  (secret manager, by design).

### 2.4 CMS (EmDash)

- `campaign-site` exists in `infra/compose/compose.yml` under profile
  `emdash`, with its database `emdash` on `core-postgres` and media in RustFS.
  `infra/pilot/compose.yml` has **no** CMS; `specs/multi-domain/PLAN.md` §6.4
  item 7 and §15 stage 0 make enabling it a prerequisite (1–2 d).
- CMS migrations are operator-only: `tools/pilot_release/migrate-cms.sh`
  (verify image identity, project-scoped lock container, close traffic with a
  durable marker, stop CMS, run `cms-migration-operator.mjs` in mode
  `verify|upgrade-v1|upgrade-v2|upgrade-emdash`). The operator refuses unknown
  or gapped EmDash migration histories, checks bindings and media guards, and
  never reopens traffic. Reopening is a manual `rmdir` of the marker.
- `pilot-release` does **not** call `migrate-cms.sh`.
- Proof: `./leonaid test-emdash-spike --case emdash-upgrade|schema-migration|migration-operator|release-legacy-boundary|release-manifest-compatibility|release-image-identity`
  (the upgrade case compares every content row, revision, media item and
  binding before and after an EmDash 0.36 → 1.4 upgrade).

### 2.5 Migration policy check

`tools/schema/check_migrations.py` rejects a forward migration that calls
`op.drop_column`, `op.drop_constraint`, `op.drop_table` or a constant
`op.execute("… DROP …")` unless the module defines non-empty
`BACKUP_REFERENCE` and `DATA_MIGRATION_REFERENCE` strings. It does not look
at `UPDATE`/`DELETE`, `DISABLE TRIGGER`, `alter_column`, renames, f-string SQL,
or whether an earlier release already stopped using what is dropped.

### 2.6 Proofs that exist

`./leonaid test-pilot-release` (v1 → v2 with real PostgreSQL, Twenty, RustFS,
Restic, Typst, Chromium; failed migration; restore; same manifest SHA
promoted again), `./leonaid test-upgrade` (Twenty/RustFS upgrade with golden
data and object-level hashes, restore of a damaged clone),
`./leonaid test-pilot-rehearsal --synthetic`, the EmDash cases above.

## 3. Findings: current risks to club content

Read from the code on 2026-11-03 (`main` at `cb4acf98`). None of these
overwrites club content today in a way a club could have noticed; several
would as soon as the product grows. Severity: **H** a realistic path to lost
or changed club content, **M** an update blocked or production left in
maintenance by club activity, **L** latent.

| #   | Sev | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| --- | --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | H   | **Migrations bypass immutability and rewrite rows by heuristic.** `0038_open_action_templates.py` disables `trg_action_template_version_immutable`, updates published template versions, and sets `presentation_theme` on every `charity_action` whose `archive_slug` matches `^krapfentaxi(?:-\|$)`. It was behaviour-preserving at the time, but the same pattern in a later release would rewrite club actions whose slug happens to match. `0037_delivery_capability.py` adds a capability to existing club actions and to published template versions (insert only, so the immutability trigger does not fire). Nothing marks which rows are shipped and which are the club's. |
| R2  | M   | **Shipped template inserts can collide with club templates.** Template keys are open slugs since 0038 (a club may publish its own templates as data; `tools/templates/contract.py` does exactly that). `0005` and `0011` insert shipped versions with plain `op.bulk_insert`, no `ON CONFLICT`. A future migration inserting e.g. `krapfentaxi` v3 or a new key the club already used fails mid-update, with production in maintenance. There is no origin column and no reserved namespace for shipped keys. |
| R3  | M   | **Club customization of the CRM blocks the update in maintenance.** `pilot-release` runs `tools/twenty/provision.py apply` *after* `pilot-deploy` and inside maintenance. The provisioner raises `SchemaDrift` when a LeonAid-managed Twenty view differs in position, size or visible fields (`view_differences`), or a managed field differs. A club admin who moves a column in a LeonAid view in the Twenty UI turns the next update into an outage until someone edits CRM views by hand. `provision.py check` exists but is not run before the backup. The step is also optional: without `--twenty-bootstrap-file` a release with new CRM fields starts Core against an old CRM schema. The ops doc says "apply … before Core starts"; `pilot-release` applies it after. |
| R4  | M   | **Strict CMS schema equality.** `requireCampaignSchema` (`apps/campaign-site/src/install-campaign-schema.mjs`) refuses any difference in the `campaign_pages` collection (`campaign_schema_drift`). If EmDash's schema editor is ever reachable for club editors, one added field stops the CMS after the next update. The editorial upgrade calls `registry.updateField(…, {validation})`; a tightened validation (shorter `maxLength`, fewer `maxItems`) silently makes existing published pages invalid for the next edit. |
| R5  | M   | **The published manifest has no CMS, and `pilot-release` has no CMS step.** The Release workflow creates schema version 1; `pilot_verify_release_manifest` expects version 1; `pilot-release` never runs `migrate-cms.sh`. Once the CMS is enabled, an update either refuses (v1 forbids `campaign-site`) or, if someone bypasses it, starts a new CMS image on an un-migrated database — which EmDash refuses, leaving campaign pages offline. |
| R6  | M   | **Backup topology not wired for the pilot** (§2.3). Fails closed, so no silent loss, but every update stops at the backup step once the CMS runs. |
| R7  | M   | **No running-campaign guard.** `pilot-release` checks the doctor and backup age, not whether an order form is open, a delivery day is today, or outbox jobs are being processed. Maintenance rejects every `POST` with `503`, so public orders during the window are lost unless the customer retries. |
| R8  | L   | **Old code never runs on the new schema.** Every rollback is a restore from the pre-update recovery point. Orders, invoices and CMS edits made after the update and before the rollback are lost (§7.4). |
| R9  | L   | **Migration policy check is narrow** (§2.5): `UPDATE`/`DELETE` on club tables, `DISABLE TRIGGER`, renames, type changes, `SET NOT NULL` and f-string SQL (0038 uses one) pass unnoticed. |
| R10 | L   | **The manifest needs a git checkout and is unsigned.** Verification reads migrations from `/opt/leonaid` at the release commit; integrity rests on GitHub TLS and the tag. The core head is taken from the last migration *file name* (`migrations[-1]`), not from the Alembic graph; `tools/pilot_release/cms_contract_test.py` guards it today. |

What is already safe and should be kept:

- Built-in action templates are **versioned and immutable** (triggers from
  `0005`; `krapfentaxi` v2 was added in `0011` as a new version, v1 untouched).
  An action keeps an immutable `action_template_snapshot`, so a new template
  version never changes an existing action.
- Survey templates (`packages/features/src/surveys/survey-templates/*.json`)
  are copied into a new survey on creation; a release only affects surveys
  created afterwards. Published survey versions are immutable.
- Legal configuration ships **no** default text: `0023` inserts only the
  state singleton; content is created by the club with four-eyes approval.
- Issued invoices are stored PDFs with SHA-256; a new Typst template is a new
  file (`invoice-v2.typ`, pinned in the manifest).
- Golden data and resets refuse anything but `LEONAID_ENV=local|test` and
  allow-listed project names (`tools/seed/golden.py`,
  `tools/seed/safety.py`).
- Core has no startup code that seeds or repairs data; all shipped rows come
  from migrations. Feature flags (`0017`), survey settings (`0027`), survey
  recovery identity (`0034`) and per-action delivery configuration (`0036`)
  are inserted once, additively.
- The Twenty provisioner only creates missing objects, fields and views and
  updates view fields only for a view it has just created.
- The EmDash operator refuses unknown histories, never imports content, and
  the upgrade proof compares every row.

## 4. Goals and non-goals

Goals:

1. G1: One published, signed, installation-independent release manifest;
   the installation only verifies against it.
2. G2: An update never changes, deletes or hides club-owned content, in Core,
   CRM, CMS or files. This is enforced by checks, not by review alone.
3. G3: The CMS is a first-class part of backup, manifest, update and proof.
4. G4: An update does not start while it would hurt a running campaign,
   unless the operator overrides it explicitly and on record.
5. G5: A failed or regretted update can be rolled back **without** losing what
   happened after it, for at least one release back.
6. G6: A club admin who is not an operations expert updates with one command
   and understands every message.
7. G7: Skipping releases works along a declared path.

Non-goals: automatic or unattended updates; updates triggered from the web
UI; multi-tenant hosting; zero-downtime updates (a short maintenance window
stays); rollback across more than one release without restore.

## 5. Part A — release vs installation

### 5.1 What the project publishes per release

Attached to the GitHub release, all covered by one signature:

| File                      | Content                                                                                                                                                                                                                                      |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `release-manifest.json`   | Schema version 3 (§5.2). The only authoritative description of the release.                                                                                                                                                                  |
| `release-images.env`      | Unchanged: image lines for the env file (kept for humans and for `pilot-*` until they are retired).                                                                                                                                         |
| `UPGRADE.md`              | Generated upgrade notes: breaking config changes, required steps, data migrations with their `DATA_MIGRATION_REFERENCE` text, minimum source version, expected window length. Rendered from the manifest plus the annotated tag body.       |
| `SHA256SUMS`              | As today.                                                                                                                                                                                                                                    |
| `SHA256SUMS.sigstore.json` | Sigstore bundle: keyless cosign signature of `SHA256SUMS`, identity = this repository's `release.yml` on a `v*` tag (GitHub OIDC). Verified on the VPS with the pinned cosign image; no key management for Björn.                          |

The six LeonAid images keep their buildx provenance/SBOM attestations; the
images are additionally signed with cosign keyless in the same job, so the
VPS can verify image identity independent of the manifest.

### 5.2 Upstream manifest v3

Extends schema version 2 (`tools/pilot_release/manifest.py`,
`cms_identity.py`); every field is installation-independent:

```json
{
  "schemaVersion": 3,
  "releaseId": "leonaid-2026.12.1",
  "version": "2026.12.1",
  "gitCommit": "<40 hex>",
  "images": { "api": "…@sha256:…", "campaign-site": "…", "twenty-server": "…", "…": "…" },
  "schemas": {
    "coreAlembicHead": "0047_…",
    "coreAlembicHeads": ["0047_…"],
    "twentySchemaSha256": "<sha of infra/twenty/schema.json>",
    "cmsEditorialSchemaVersion": 3,
    "cmsUpstreamMigrations": ["001_…", "…", "091_…"]
  },
  "migrations": [{ "revision": "…", "path": "…", "sha256": "…", "phase": "expand|contract|data", "contractsExpand": "0045_…" }],
  "cms": { "package": {}, "editorialSchemaVersion": 3, "sources": {} },
  "config": { "schemaSha256": "…", "version": 4, "migrations": ["config/0004_admin_domain.json"] },
  "upgrade": {
    "minSourceVersion": "2026.9.1",
    "stepStones": ["2026.10.2"],
    "rollbackCompatibleWith": "2026.11.3",
    "steps": ["queue-store", "rustfs", "twenty-upgrade", "twenty-schema", "core-migrate", "cms-migrate"],
    "expectedWindowMinutes": 15
  },
  "artifacts": { "compatibilityMatrix": {}, "invoiceTemplate": {}, "openapi": {}, "upgradeNotes": {} },
  "requiredGates": ["…"],
  "rollback": { "core": "previous_release_on_new_schema", "twenty": "backup_restore_after_migration", "rustfs": "…", "cms": "…" }
}
```

Changes against v2:

- `campaign-site` is always present (an installation without the CMS simply
  does not start the profile; the image is still part of the release).
- `coreAlembicHeads` is computed from the Alembic graph, not from the last
  file name (R10).
- Each migration declares its **phase** (§7.2); a contract names its expand.
- `upgrade` declares the supported source range, mandatory stepping stones and
  the previous release that runs on this schema (§7, §9).
- `config` binds the env schema and the declarative env migrations (§9.3).
- No `deploymentMode`: a published manifest is always `production`. Test
  manifests stay possible through `--deployment-mode test` in tests only.

### 5.3 Local verification instead of a local manifest

The per-installation manifest of `RELEASE-RUNBOOK.md` §1 is dropped. It adds
no information: its images come from `release-images.env`, its migrations
from the same commit. Its only effect is a SHA that differs per installation,
which makes the ledger harder to compare with the published release.

Instead, `./leonaid update` (and `pilot-deploy`/`pilot-release` while they
exist) runs **`release verify-installation`**:

1. Verify the Sigstore bundle against `SHA256SUMS`, then the manifest and
   notes against `SHA256SUMS`.
2. Verify the checkout (or bundle, §5.4) is exactly `gitCommit`, and every
   migration, artifact and CMS source SHA (as today).
3. Verify inside the **pulled core image** that its `migrations/versions`
   equal the manifest list (one `python -m leonaid.entrypoints.release_identity`
   run, `--network none`). Today only the checkout is compared; the image
   could differ.
4. Render the effective Compose configuration from the installation's env
   file and the release's Compose files; require that every image equals the
   manifest. The env file holds **no image lines any more**: images come from
   the manifest through a generated, read-only
   `/var/lib/leonaid/releases/<version>/images.env` passed as a second
   `--env-file`. This removes the copy-paste step and the drift class
   "operator pasted the wrong line".
5. Validate the env file against the release's config schema (§9.3).
6. Run the existing deployment contract (`tools/pilot_deployment/validate.py`):
   ports, mounts, no build, no floating tag.

### 5.4 Where the release lives on the VPS

Today: a git checkout at `/opt/leonaid`, switched to the release commit. Keep
this for now (it works, `./leonaid` and all Compose files come from it), with
two changes:

- `./leonaid update` performs `git fetch --tags` and
  `git checkout --detach v<version>` itself, after verifying that the tag's
  commit equals the signed manifest's `gitCommit`. The club admin never runs
  git by hand.
- The update is **two-phase** because the CLI replaces itself: the running
  (old) CLI downloads, verifies, writes `/var/lib/leonaid/update/plan.json`,
  switches the checkout and `exec`s the new CLI with `update --continue
  <plan>`. Only the new CLI knows the new release's migration steps.

Later option (not in this plan): a signed release bundle
`leonaid-<version>.tar.gz` with only `leonaid`, `infra/` and the tools the
operator commands need, so the VPS needs no git. Decide after the first real
update cycle (open question Q2).

### 5.5 Installation state and what stays of the ledger

A new file `/var/lib/leonaid/installation.json` (0600, owned by the
operations account) replaces "which manifest is current" by convention:

```json
{
  "installationId": "<random uuid, created by pilot-install>",
  "release": { "version": "2026.11.3", "manifestSha256": "…", "since": "…" },
  "previous": { "version": "2026.11.2", "manifestSha256": "…" },
  "configVersion": 3,
  "lastRecoveryPoint": { "snapshotId": "…", "manifest": "…", "createdAt": "…" },
  "pendingUpdate": null
}
```

The release ledger stays, unchanged in format and rules (append-only, PII-free,
evidence IDs), with three changes:

- It records the **upstream** manifest SHA, so "this club runs exactly the
  published 2026.11.3" is checkable from the outside.
- Events gain `rehearsal_started|rehearsal_verified` (§8.3),
  `update_started|update_verified|update_failed`,
  `rollback_*`, and `guard_overridden` with the operator's reason (§6.6).
- The "production only after staging with the same SHA" rule becomes "update
  only after a rehearsal with the same SHA" when the club has no separate
  staging installation (§8.3). A club that has one keeps today's rule.

`--evidence-id` stays optional for clubs: the update writes its own evidence
ID (`UPD-<version>-<timestamp>`) and the human browser check becomes a
prompt (§8.2 step 10), not a precondition.

## 6. Part B — CMS fully covered

### 6.1 Backup and restore

- `pilot-backup`, `backup`, `pilot-restore` and `restore` derive the topology
  from the installation instead of a variable: `emdash` when the `emdash`
  database exists or the `emdash` profile is enabled in the env file
  (`COMPOSE_PROFILES`), else `legacy`. The fail-closed check of
  `backup.sh` stays.
- The recovery point contains: `emdash.dump`, `cms-bootstrap-state.tar`, the
  `emdash-media` bucket (already in the RustFS volume) and the CMS image
  reference. The CMS encryption key (`CMS_ENCRYPTION_KEY`) is a secret and stays
  out of the backup; `pilot-doctor` checks it exists in the secret manager
  copy (same treatment as the Restic password).
- The backup doctor reports CMS counts (pages, published pages, revisions,
  media objects) in the sanitized backup manifest, so a restore can be
  checked against numbers without reading content.

### 6.2 CMS in the update flow

`pilot-release` / `update` gains a `cms-migrate` step, run only when the
CMS profile is enabled, after Core migrated and before maintenance ends:

1. Pre-flight (before backup): `migrate-cms.sh … verify` under the
   **current** image; refuses drift (R4) before anything changes.
2. If the editorial schema version rises: `upgrade-v<N>` under the current
   image, as `migrate-cms.sh` requires today ("upgrade-v1/v2 run under the
   previous image"). This becomes a declared step in the **previous** release
   so that a jump does not need the old image later (§9.1).
3. Recreate `campaign-site` on the new image with `--no-start`;
   `migrate-cms.sh … upgrade-emdash` when `cmsUpstreamMigrations` grew,
   else `verify`.
4. Reopen CMS traffic (remove the marker) **in the CLI**, not by a manual
   `rmdir`, only after `verify` passed and the published-page check (§6.3)
   is green.

Rule for editorial schema changes (fixes R4): a new editorial version may add
fields and **loosen** validation. Tightening requires a pre-flight query that
counts existing entries and revisions that would violate the new rule; the
update refuses with that number (no content is changed to make it fit).

### 6.3 Published campaign page survives unchanged

New proof `./leonaid test-emdash-spike --case release-update-content` (and the
same check inside `update` on the real installation, read-only):

- Before the update: for every published `campaign_pages` entry record the
  content row hash, latest revision hash, bound action, media object keys with
  SHA-256, and a **normalized render** of the public URL (HTML with nonces,
  asset hashes and build IDs removed, text and links kept).
- After the update: rows, revisions and media must be byte-identical (except
  for documented upstream data migrations such as EmDash `079` date
  normalization, which the proof compares semantically, as
  `emdash-upgrade` does today). The normalized render must have the same text,
  headings, links and image sources. Theme/CSS changes are allowed only when
  the release notes declare them; the proof stores a screenshot diff as
  evidence, not as a gate.
- On the real installation the same snapshot runs before maintenance and
  after; a difference keeps CMS traffic closed and reports which page.

### 6.4 Prerequisite

Enabling the CMS in the pilot (`specs/multi-domain/PLAN.md` §15 stage 0) must
land together with §6.1 and manifest v3. Order in §14.

## 7. Part C — protecting club content

### 7.1 Ownership classes

Every table gets one class in a new registry `migrations/ownership.json`
(checked by CI: every table created by a migration must be listed):

| Class       | Meaning                                                                                       | Examples                                                                                           |
| ----------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `club`      | Created and changed by people. A release never updates or deletes rows.                      | `charity_action`, `commitment`, `invoice`, `user_account`, `legal_configuration_version`, `survey*`, `task*`, `knowledge*`, `material*`, CMS content and revisions of `campaign_pages` |
| `catalogue` | Mixed: shipped defaults and club rows in one table, distinguished per row (§7.2).            | `action_template_version` and its child tables, `feature_flag`                                     |
| `system`    | Technical state the product owns and may rewrite: queues, claims, rate limits, caches.        | `outbox_event` (claim columns), `security_rate_attempt`, `command_receipt`                         |
| `singleton` | One row created by a migration, then edited by the club.                                     | `survey_settings`, `legal_configuration_state`                                                     |

### 7.2 Rules for shipped defaults

1. **Seed only if absent.** Shipped rows are inserted with
   `ON CONFLICT DO NOTHING`, keyed by a stable natural key, never by a
   generated ID.
2. **Never update a club row, never update a shipped row the club changed.**
   For `catalogue` tables, a shipped row may be updated only while it is
   provably untouched (§7.3). Immutable kinds (template versions) are never
   updated at all.
3. **New defaults are new options.** A changed default ships as a new
   version (`krapfentaxi` v3) or a new key, next to the old one. Existing
   actions keep their snapshot; the club chooses when to use the new version.
   Retiring a shipped version means `is_available = false` only when the
   club has not changed that flag.
4. **Reserved namespace.** Shipped keys get the `leonaid-` prefix from the
   next new template on (`leonaid-golf-tournament`); existing `blank` and
   `krapfentaxi` are grandfathered. Club keys may not start with `leonaid-`
   (CHECK). This removes collision R2.
5. **Feature flags and settings.** A new flag is inserted with its default;
   an existing flag's value is never flipped by a release. Changing a default
   for new installations only is done in the seed, not with `UPDATE`.
6. **Copy-on-create stays the model** for survey templates and similar
   frontend-bundled content: a release changes what new objects start with,
   never existing objects.

### 7.3 Detecting "club-modified"

`catalogue` and `singleton` tables gain three columns:

| Column          | Meaning                                                                               |
| --------------- | ------------------------------------------------------------------------------------- |
| `origin`        | `shipped` or `club`. Default `club`; only migrations write `shipped`.                 |
| `shipped_from`  | Release version that inserted or last updated the row (`2026.12.1`), null for club rows. |
| `shipped_hash`  | SHA-256 of the canonical JSON of the row's editable columns as shipped.              |

A row is **club-modified** when `origin = 'shipped'` and the current hash of its
editable columns differs from `shipped_hash`. A SQL function
`leonaid_row_is_pristine(table, key)` computes this; migrations may update a
shipped row only inside `WHERE leonaid_row_is_pristine(…)` and must report
how many rows they skipped (written to `release_migration_report`, read by
the update report). Backfill for existing rows: `blank`/`krapfentaxi`
versions get `origin = 'shipped'` with the hash of their current content;
every other row `club`.

For Twenty (R3): LeonAid-managed objects, fields and views are identified by
the fixed IDs in `infra/twenty/schema.json`. Structural drift (field type,
relation, missing managed field) still blocks. **Presentation drift** of a
managed view (position, size, visibility of columns, view order) is club
customization: the provisioner keeps it, logs it, and stops treating it as
`SchemaDrift`. New managed views are created; existing views are not touched.

For the CMS (R4): the `campaign_pages` collection is LeonAid-owned; content
in it is club-owned. Any additional collection the club creates is club-owned
and must not cause `campaign_schema_drift` (the check compares the LeonAid
collection only, which it already does; the rule is recorded so it stays so).

### 7.4 Rules for data migrations

Allowed in a forward migration (phase `expand` or `data`):

- `CREATE TABLE`, `ADD COLUMN` nullable or with a constant default,
  `CREATE INDEX`, `ADD CONSTRAINT … NOT VALID` followed by `VALIDATE`
  in a later migration.
- Inserting shipped rows with `ON CONFLICT DO NOTHING` (§7.2).
- **Backfill of a column this migration added**, set only where it `IS NULL`,
  derived from the same row or its parents, deterministic, idempotent
  (running it twice changes nothing). Example: `0036` (one delivery
  configuration per action), `0033` (retention start).
- Updating `system` tables.
- Updating `catalogue`/`singleton` rows only where pristine (§7.3).

Forbidden in any forward migration:

- `UPDATE`/`DELETE` on `club` tables other than the backfill above.
- Selecting rows by name or slug heuristics (`WHERE archive_slug ~ …`, R1).
- `DISABLE TRIGGER` / `ALTER TABLE … DISABLE`, `session_replication_role`.
- `TRUNCATE`.
- Dropping or renaming anything still read by the previous release
  (§8.1 two-release rule).
- Non-deterministic values in data (`now()` is fine only for audit columns).

Each migration with data effect declares `DATA_MIGRATION_REFERENCE` (exists)
plus a machine-readable `DATA_EFFECT = {"tables": {...}, "kind":
"backfill-new-column|insert-shipped|update-pristine|system"}`.

### 7.5 The check that enforces it

Replace `tools/schema/check_migrations.py` with a policy check (still pure
AST, runs in `./leonaid check` and CI):

1. Parse `upgrade()` including helper functions it calls, and every SQL
   string: constants, f-strings (render with placeholders), `sa.text`,
   `op.bulk_insert`. Classify statements with a small SQL tokenizer
   (`sqlglot` is not a dependency today; a tokenizer for the statement head
   and target table is enough).
2. Map each target table to its ownership class (`migrations/ownership.json`).
3. Reject forbidden operations (§7.4) unless the migration is listed in a
   reviewed waiver file `migrations/policy-waivers.json` with reason,
   reviewer, and the release it shipped in. Existing migrations `0001`–`0044`
   are grandfathered by an explicit list with their SHA-256, so editing an old
   migration is also caught.
4. Require `phase` and, for contract migrations, `CONTRACTS_EXPAND` pointing
   to a migration that is in the **previous published manifest** (§8.3).
5. A runtime companion: `tools/schema/club_content_test.py` loads golden data
   plus a "club-modified" fixture (edited shipped template availability,
   club template with a colliding-looking key, club feature flag values,
   edited legal draft, a CRM view with moved columns, a CMS page with all
   field types), runs `alembic upgrade head` from the previous release's head,
   and compares every `club` row and every club-modified `catalogue` row
   byte-for-byte (excluding declared backfill columns). This runs in CI on
   every migration change.

## 8. Part D — update guard for running campaigns

### 8.1 What is checked

A read-only Core entrypoint `python -m leonaid.entrypoints.update_guard --json`
(runs in the current `api` image, no network besides the database) returns
findings with a level:

| Check                                                                                                                       | Level         | Why                                                                                      |
| --------------------------------------------------------------------------------------------------------------------------- | ------------- | ---------------------------------------------------------------------------------------- |
| An `active` action with the `ordering` capability whose order form is public and accepting (offering availability covers now) | **block**     | Maintenance answers public `POST` with `503`; orders in the window are lost.             |
| A delivery window (`action_delivery_window.delivery_on`) today or tomorrow before 10:00 local time (club time zone)          | **block**     | Drivers and dispatchers use the PWA during delivery.                                     |
| Outbox events in `processing` with a live claim                                                                             | **block** (wait) | A claim cut by the worker stop may duplicate or delay mails; the guard waits up to 5 min for claims to finish, then blocks. |
| Outbox events `pending` older than 10 min, or any `dead_letter` newer than 24 h                                             | warn          | Mail is backed up already; the update would add delay. Pending events survive maintenance. |
| Survey open with a participation in the last 30 min                                                                          | warn          | Respondents get `503` on submit and must resume.                                         |
| CMS editor or admin session active in the last 15 min                                                                        | warn          | Unsaved editor work is lost when CMS traffic closes.                                     |
| Import or four-eyes approval in progress (legal configuration draft awaiting approval is fine; an apply running is not)     | **block**     | Half-applied operator flows.                                                             |
| Recovery point older than 26 h, free disk < max(5 GiB, 2 × last backup size + new images), free RAM < 1 GiB               | **block**     | Same thresholds as `pilot-doctor`, plus room for images and backup staging.              |
| A restore or rehearsal project of this installation is running                                                             | **block**     | Memory budget (§10.3).                                                                   |

The guard runs twice: at plan time (`update --check`) and again right before
maintenance starts.

### 8.2 Override

- `warn` findings: shown, then one confirmation.
- `block` findings: refuse unless `--override-guard "<reason>"` is given and
  the operator types the release version back. The reason is stored in the
  ledger as `guard_overridden` (reason text kept to 200 chars, no PII check
  beyond length; the docs ask for a reason like "delivery done, form closed by
  phone").
- Never overridable: live outbox claims after the wait, a running restore,
  disk/RAM below the minimum, an unsigned or mismatching manifest.
- `update --at 02:30` schedules the update once through a transient systemd
  timer (`systemd-run --on-calendar`) and re-runs the guard at that time; a
  block then aborts without changes and leaves a report.

### 8.3 What the operator sees

```text
LeonAid update 2026.11.3 → 2026.12.1

  ✔ Release signature and manifest verified (signed by BjoernSchotte/leonaid release workflow)
  ✔ Configuration: 1 new optional setting (LEONAID_ADMIN_DOMAIN, empty = unchanged)
  ✔ Backup: last recovery point 3 h old; a fresh one is taken before the update
  ✘ Campaign "Krapfentaxi 2026": public order form is open (closes 14.02. 18:00)
  ✘ Delivery day: "Krapfentaxi 2026" delivers tomorrow 16.02.
  ! 2 mails waiting in the outbox for more than 10 minutes

Not started. Choose a quiet time, for example after the delivery:
  ./leonaid update 2026.12.1 --at "2026-02-16 22:00"
To update anyway (the order form is unavailable for ~15 minutes):
  ./leonaid update 2026.12.1 --override-guard "reason"
```

The public order form and the campaign page show a maintenance notice with
the expected end time instead of a bare `503` (small change in `apps/public`
and `campaign-site`; Core already sends `Retry-After`).

## 9. Part E — rollback without data loss

### 9.1 Expand/contract, two-release rule

Every schema change that removes or changes something is split:

1. **Release N (expand):** add the new shape; write both shapes (or derive
   the old from the new through a view/trigger); read the new one with a
   fallback. Migrations are `phase: expand`.
2. **Release N+1 (contract):** drop the old shape. Migration `phase: contract`
   with `CONTRACTS_EXPAND = "<expand revision>"`, and that expand revision
   must appear in the previous published manifest.

Consequence: the code of release N−1 runs on the schema of release N. The
manifest states it as `upgrade.rollbackCompatibleWith = <N−1>`. A release
that cannot keep this (rare: e.g. a Twenty major upgrade) says
`rollbackCompatibleWith: null` and the update tells the operator up front that
rollback means restore.

### 9.2 What "previous release runs on the new schema" requires

- Core: Alembic version table at N's head while N−1 code runs. N−1 must not
  check the head strictly at startup. Today `pilot_release_migrate` checks
  `alembic current` only after migrating, and the API does not check the head
  at startup, so this already holds; a startup check must allow "head ∈
  known descendants of my head" from the manifest.
- Core: new tables and nullable columns are ignored by N−1; new NOT NULL
  columns need a default; new CHECK values must not be written by N while N−1
  could still read them as invalid, or N−1 must treat unknown enum values as
  "unknown" (rule for domain enums: parse leniently on read).
- Outbox: N may only emit new event types that N−1's worker parks instead of
  dead-lettering. Today `parked_event_types` exists for disabled modules; the
  worker gains "unknown event type → park, keep, retry after update".
- CMS: EmDash upstream migrations are forward-only. CMS rollback stays
  restore-only (CMS SQL + media + bootstrap state of the same recovery point),
  with the existing rule "preserve later Core orders": restoring the CMS does
  not touch Core.
- Twenty, RustFS, Valkey, PostgreSQL major: as today, rollback boundary per
  `compatibility-matrix.json`; mostly restore after first write.

### 9.3 CI check for destructive migrations

Part of the policy check (§7.5 item 4):

- A `contract` migration without a resolvable `CONTRACTS_EXPAND` fails.
- A `drop_column`/`drop_table`/`rename`/type change/`SET NOT NULL` in a
  migration marked `expand` fails.
- The check loads the latest published `release-manifest.json` (cached in CI
  from the GitHub release) and requires the expand revision to be in it;
  "expand and contract in the same release" fails.
- New test `./leonaid test-release-rollback`: start release N−1 images on a
  database migrated to N with golden data, run the golden journey read paths
  and one order write, then start N again and verify both writes. Runs in the
  Release workflow before publishing and refuses to set
  `rollbackCompatibleWith` when it fails.

### 9.4 When restore is still necessary, and what is lost

| Situation                                                                 | Rollback                                    | Lost                                                                                                                       |
| ------------------------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| N has a bug, schema compatible (`rollbackCompatibleWith = N−1`)           | `./leonaid rollback`: start N−1 images on the current data | Nothing. Data written by N stays; N−1 ignores new columns.                                                                  |
| Migration failed half-way (inside maintenance)                            | Restore the pre-update recovery point       | Nothing: maintenance blocked writes since the backup.                                                                       |
| Twenty/RustFS/CMS upstream migration ran, then a problem appears          | Restore that component from the pre-update point | Writes to that component since the update: CRM edits, CMS edits/media uploads, stored documents (RustFS). Core orders stay if only Twenty/CMS is restored. |
| Problem found days later and N−1 cannot run (incompatible release)        | Restore everything                          | **Everything since the update**: orders, invoices, payments, member changes, CMS edits. The update report shows this risk before the update starts. |
| Data corruption by a bad data migration                                   | Restore Core into a side project, compare, re-apply by hand | Depends; this is what §7 prevents.                                                                                       |

The update keeps the pre-update recovery point (Restic tag
`pre-update-<version>`) out of normal rotation for 30 days.

## 10. Part F — operator experience

### 10.1 One command

```sh
./leonaid update               # shows available releases and what would happen
./leonaid update 2026.12.1     # does it
./leonaid update --check 2026.12.1
./leonaid update --continue    # resume after a fixed blocker
./leonaid rollback             # to the previous release, if compatible
./leonaid update-status        # what runs, last update, last report
```

Inputs come from fixed places, not flags: env file `/etc/leonaid/production.env`
(or `LEONAID_ENV_FILE`), secrets under `/etc/leonaid/secrets/`, state in
`/var/lib/leonaid/`. The existing `pilot-*` commands stay as the expert layer;
`update` calls them.

### 10.2 Phases

| #  | Phase                    | What happens                                                                                                                       | Writes?          |
| -- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| 1  | Discover                 | GitHub releases API; list newer versions, notes, required path (§11).                                                             | no               |
| 2  | Download + verify        | Manifest, notes, sums, Sigstore bundle; verify signature and hashes; `git fetch --tags`; tag commit = manifest commit.            | `/var/lib/leonaid/update/` |
| 3  | Pull images              | `docker pull` by digest; verify cosign signatures of LeonAid images; core image migration identity (§5.3 step 3).                  | image store      |
| 4  | Pre-flight               | Config schema + env migration dry-run (§11.3); deployment contract; `pilot-doctor`; Twenty `provision.py check`; CMS `verify`; update guard; disk/RAM. | no               |
| 5  | Plan + confirm           | Print plan, window estimate, rollback mode ("rollback keeps data" or "rollback needs restore: data since now would be lost"). One confirmation. | no               |
| 6  | Switch CLI               | Checkout tag, `exec` new CLI with plan (§5.4).                                                                                     | checkout         |
| 7  | Backup                   | Fresh recovery point incl. CMS; tag `pre-update-<version>`; `restic check`.                                                       | backup repo      |
| 8  | Maintenance              | `maintenance.sh enable`; verify write rejection; close CMS traffic.                                                               | maintenance flag |
| 9  | Migrate                  | Env migration (atomic, old file kept 0600) → queue store → RustFS → Twenty upgrade → Twenty schema → Core Alembic → CMS (§6.2).   | yes              |
| 10 | Start + verify           | `up --no-build`; doctor; golden read journey against real data (read-only probes); published-page check (§6.3); counts of club rows unchanged (actions, commitments, invoices, users, CMS pages, media). Then prints the URLs to check in a browser and asks "Looks right? [y/N]". | no |
| 11 | Release                  | Lift maintenance, reopen CMS; update `installation.json`; ledger `update_verified`.                                                 | state            |
| 12 | Report                   | `/var/lib/leonaid/update/<version>/report.json` + human summary: duration, skipped shipped-row updates (§7.3), guard overrides, warnings. | file             |

On failure after phase 8 the CLI keeps maintenance, prints one of three
plain next steps ("retry with `--continue` after fixing X", "`./leonaid
rollback`", "restore — run `./leonaid restore-pre-update`") and records
`update_failed`. Messages say what happened and what to do, never only a
code; the code is printed after for support.

### 10.3 Rehearsal on the same VPS

For clubs without a staging installation (the normal case), `./leonaid
update --rehearse 2026.12.1`:

1. Restore the **latest** recovery point into a temporary project
   `leonaid-rehearsal-<version>` (existing restore code path with fresh
   volumes and confirmation; target env generated from the production env
   with different project, ports bound to `127.0.0.1` only, no Caddy, no mail
   (SMTP to a blackhole), no CRM sync job, no backup timer, alerting off).
2. Run phases 7–10 against it with the new release; the same guard and
   checks.
3. Print the result and an SSH tunnel command to look at the rehearsal in a
   browser; on confirmation record `rehearsal_verified` for the manifest SHA.
4. Remove the project and its volumes (the name pattern guarantees it never
   touches production).

Memory budget (from
`apps/docs/src/content/docs/en/ops/reference/services-ports-and-commands.md`):
production limits sum to 5.9 GiB (6.4 GiB with monitoring), observed idle
~1.7 GiB, peak ~2.4 GiB. A second full stack does not fit by limits. The
rehearsal therefore:

- runs with a reduced overlay: `twenty-worker` off, `twenty-server` limit
  1.4 GiB (enough for `command:prod upgrade` at ~1.1 GiB RSS), web/pwa off
  (static, unchanged by data), monitoring off — rehearsal limits ~3.3 GiB;
- requires `MemAvailable ≥ 3.5 GiB` at start and stops itself if it falls
  below 512 MiB (watchdog loop in the CLI);
- runs ideally at night; the guard warns when production had traffic in the
  last 10 minutes.

Disk: restored volumes (≈ size of the last backup, uncompressed) + new images
(≈ 3–4 GiB for a release that changes all LeonAid images; Twenty only when
its pin changes) + backup staging. The pre-flight requires
`free ≥ 2 × backup size + image delta + 5 GiB` and prints the numbers.

A club with real staging keeps using it; `--rehearse` is the default
recommendation in the docs, not mandatory (open question Q4).

### 10.4 "New version available" in the admin UI

- A systemd timer `leonaid-update-check.timer` (daily, randomized) runs
  `./leonaid update --discover --json` and writes
  `/var/lib/leonaid/update/available.json` (version, date, notes URL,
  security flag, required path, last guard summary). Signature verified.
  Opt-out: `LEONAID_UPDATE_CHECK=off`. The check sends no installation data;
  it is an anonymous GitHub API call.
- Core mounts the file read-only and exposes it on an admin-only endpoint
  `GET /api/v1/admin/system/update` (system admin role).
- The admin UI shows a dismissible banner for system admins: "LeonAid
  2026.12.1 is available (security fix). Ask your technical contact to run
  `./leonaid update 2026.12.1`." Plus the current version in the system page.
- **No trigger from the web UI**, no endpoint that starts anything, no write
  path from Core to the host. The UI part waits for the current UI migration
  (`feat/leitsystem`) to land.

## 11. Part G — multi-version jumps, config migrations, multi-domain

### 11.1 Jumps and stepping stones

- Core Alembic migrations run in order, so jumping N → N+3 is the same as three
  hops for Core **if** data migrations are pure SQL (they are) and do not
  depend on code of an intermediate release. The policy check forbids
  importing application code in migrations.
- The expand/contract rule only guarantees N−1 on N. A jump N → N+2 applies
  expand and contract in one window; that is fine forward, and rollback is to
  N+1's compatibility, i.e. restore for the jump. The plan says so.
- Third-party components may need ordered hops (Twenty requires passing
  certain versions; RustFS/PostgreSQL majors). The CMS editorial upgrade must
  run under the old image (§6.2). Such releases are marked as **stepping
  stones** in later manifests (`upgrade.stepStones`).
- `update` computes the path from `installation.json` to the target:
  current → each stepping stone → target. Each hop is a full cycle
  (phases 2–11) but with **one** backup at the start of the whole path and a
  lightweight verify per hop; the operator confirms once. A failure rolls back
  to the path's start backup.

### 11.2 Minimum supported upgrade path

- Every release declares `minSourceVersion`: the oldest release from which a
  direct jump is tested. Proposal: all releases of the last 12 months, and
  never older than the last stepping stone.
- The Release workflow runs `test-pilot-release` from `minSourceVersion` and
  from N−1 to N with golden data before publishing (two jobs; ~40 min each).
- Older installations must first update to a stepping stone; `update` prints
  the path instead of refusing silently.

### 11.3 Config (env file) migrations

- The release ships `infra/config/schema.json` (keys, type, required/optional,
  default, secret flag, deprecated/renamed) and declarative steps
  `infra/config/migrations/NNNN_*.json`, versioned like Alembic
  (`configVersion` in `installation.json`).
- Allowed step kinds: add optional key with default; rename key (keep value);
  derive a key from others (e.g. a base URL from a domain); mark deprecated.
  Never generate or rotate a secret silently, never invent a domain.
- A required key without a safe default is a pre-flight **block** with a
  plain question ("Which host should the admin interface use? Set
  `LEONAID_ADMIN_DOMAIN` in /etc/leonaid/production.env, then
  `./leonaid update --continue`").
- Writing: atomic replace, mode `0600`, old file kept as
  `production.env.<old-version>` next to it; the diff (keys only, values of
  secrets masked) goes into the report.
- With image lines out of the env file (§5.3 step 4), the first config
  migration removes `LEONAID_*_IMAGE`, `LEONAID_SERVICE_VERSION` and
  `LEONAID_RELEASE_COMMIT` from the env file (they come from the manifest).

### 11.4 Interaction with the multi-domain plan

`specs/multi-domain/PLAN.md`:

- Stage 0 (CMS in the pilot) depends on Part B (§6.1, §6.2) and manifest v3.
  Do them together; otherwise the first update after enabling the CMS fails
  at the backup (R6) or the manifest (R5).
- Stage 1 adds `LEONAID_ADMIN_DOMAIN` and `LEONAID_PUBLIC_DOMAIN_ALIASES`.
  Empty means single-host mode (multi-domain G4), so the config migration adds
  them empty; switching to an admin host is a club decision done later with
  its own command, not by the update.
- Stage 2 adds `site_host`/`site_binding`: club data (`club` class), in Core
  backups automatically. Caddy certificates for club domains are not in the
  backup today; after a full restore on a new host, Caddy re-issues them via
  on-demand TLS (rate limits: Let's Encrypt 50 certificates per registered
  domain per week — fine for a club). The multi-domain plan §10.1 should be
  corrected ("Caddy data is not in backups").
- Multi-domain migrations must follow §7.4 and §9.1 (e.g. alias migration
  §7.7.7 there is an expand; dropping old alias columns is a later contract).

## 12. Test plan

| Level        | Test                                                                                                                                                                                                                          |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit         | Manifest v3 create/verify (graph heads, phases, stepping stones, config binding); Sigstore verification with a test bundle and a forged one; path computation (§11.1); config migration engine (add/rename/derive, refusal of required-without-default, secret masking); guard rules with fixed clocks and time zones (delivery tomorrow 09:59 vs 10:01, DST). |
| Policy       | `check_migrations` v2 against fixtures: every forbidden pattern of §7.4 incl. f-string SQL and helper functions; grandfathered SHA list catches an edited old migration; contract without expand in previous manifest fails. |
| Club content | `club_content_test.py` (§7.5): previous head → head with club-modified fixtures; byte compare of club rows; pristine shipped row updated, modified one skipped and reported.                                                     |
| CRM          | Provisioner with a club-reordered managed view: apply keeps it, check reports it as customization, structural drift still blocks.                                                                                              |
| CMS          | `test-emdash-spike --case release-update-content` (§6.3); editorial schema tightening refused with a count; club collection does not trip drift; backup/restore with derived topology.                                        |
| Rollback     | `test-release-rollback` (§9.3): N−1 images on N schema, read journey + order write, back to N.                                                                                                                                 |
| End-to-end   | `test-pilot-release` extended to `update`: signed test manifest (local Sigstore test identity), N−1 → N with CMS, guard block + override recorded, env migration, failed Core migration → maintenance kept → `restore-pre-update`, rehearsal project created and removed with a memory ceiling. |
| Jump         | `minSourceVersion` → N and stepping-stone path, in the Release workflow.                                                                                                                                                        |
| Manual       | First real club update via `--rehearse`, then real update in a window; acceptance record as today.                                                                                                                             |

## 13. Effort estimate

Developer days including tests and docs (English and German ops docs),
excluding Björn's review.

| Part | Scope                                                                                                                                       | Days    |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| A1   | Manifest v3, graph heads, phases field, `release verify-installation`, core-image migration identity, images out of the env file           | 3–4     |
| A2   | Sigstore signing in `release.yml` (manifest sums + images), verification with pinned cosign image                                           | 1–2     |
| A3   | `installation.json`, ledger events, retire per-installation manifest in runbooks                                                           | 1–2     |
| B    | CMS: derived backup topology, CMS step in update, reopen in CLI, editorial-tightening pre-flight, published-page proof                     | 4–5     |
| C1   | Ownership registry, `origin/shipped_*` columns + backfill migration, pristine function, `leonaid-` namespace CHECK                         | 2–3     |
| C2   | Policy check v2 (SQL classification, grandfather list, waivers), `club_content_test.py` with fixtures                                      | 3–4     |
| C3   | Twenty provisioner: presentation drift tolerated, `check` in pre-flight, schema apply before Core starts and mandatory                     | 1–2     |
| D    | Update guard entrypoint, override + ledger, `--at` scheduling, maintenance notice in public/CMS                                             | 3–4     |
| E    | Expand/contract rules in the policy check, lenient enum reads + unknown outbox types parked, `test-release-rollback`, `rollback` command    | 4–6     |
| F1   | `./leonaid update` orchestration (two-phase CLI, phases, report, `--continue`, `restore-pre-update`)                                      | 4–6     |
| F2   | Rehearsal on the same VPS (reduced overlay, memory watchdog, cleanup)                                                                       | 2–3     |
| F3   | Update-check timer + admin endpoint; UI banner after the UI migration                                                                       | 1–2 (+1 UI) |
| G    | Path computation, stepping stones, config schema + migrations engine, Release workflow jump tests                                         | 3–4     |
|      | **Total**                                                                                                                                   | **32–48 (+1)** |

## 14. Recommended order

1. **C2 + C3 first** (policy check, club content test, Twenty pre-flight).
   Cheap, protects every following release, and fixes R3 which can cause an
   outage today.
2. **C1** (ownership + origin columns) before any new shipped template or
   flag; fixes R1/R2 by construction.
3. **A1 + A3** (manifest v3, local verification, installation state): the
   base for everything else; retires the per-installation manifest.
4. **B together with multi-domain stage 0** (CMS in the pilot): fixes R5/R6
   before the CMS goes live.
5. **D** (guard): before the first update during a campaign season.
6. **F1** (`./leonaid update`) on top of the existing `pilot-release`
   internals; then **F2** (rehearsal).
7. **A2** (signing) — can move earlier; independent, small.
8. **E** (expand/contract, N−1 rollback): start the rule now in reviews;
   tooling once F1 exists.
9. **G** (jumps, config migrations) before multi-domain stage 1 ships its env
   keys.
10. **F3** (update notice) after the UI migration.

## 15. Open questions for Björn

| #   | Question                                                                                                                                                                                    | Proposal                                                                         |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Q1  | Sign with Sigstore keyless (identity = the GitHub workflow) or with a project key you hold?                                                                                                 | Keyless; no key to lose, verifiable by anyone.                                    |
| Q2  | Keep the git checkout on the VPS, or move to a signed release bundle without git?                                                                                                          | Keep git now; decide after the first real update cycle.                           |
| Q3  | Guard thresholds: delivery day block "today and tomorrow before 10:00"? Order form open = block or warn?                                                                                    | Both block, with override.                                                        |
| Q4  | Is a same-VPS rehearsal mandatory before every update, recommended, or only for releases with data/third-party migrations?                                                                 | Mandatory when the manifest has `data`/`contract` phases or third-party steps; otherwise recommended. |
| Q5  | Support window: direct jumps from all releases of the last 12 months?                                                                                                                       | Yes, plus stepping stones.                                                        |
| Q6  | Shipped key namespace `leonaid-` for new templates — acceptable for display (only the display name is shown to users)?                                                                      | Yes.                                                                              |
| Q7  | May clubs customize LeonAid-managed CRM views (column order/visibility) and keep them across updates?                                                                                       | Yes, presentation only.                                                           |
| Q8  | Update check: contact GitHub by default (opt-out) or off by default (opt-in)?                                                                                                               | On by default, opt-out; no installation data sent.                                |
| Q9  | Do we keep the separate staging installation in the pilot (two domains, two Restic repos), or replace it with the same-VPS rehearsal for the pilot club as well?                            | Keep staging during the pilot; rehearsal for all later clubs.                     |
| Q10 | Should `update` run unattended at `--at` time without a human for the final "looks right" prompt?                                                                                          | Yes, but then only automatic checks gate, and the report asks for a browser check the next morning. |
