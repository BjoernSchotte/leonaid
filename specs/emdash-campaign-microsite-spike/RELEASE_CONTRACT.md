# CMS release manifest contract

Version 1 remains the default, pre-CMS release contract. It requires exactly the
existing twelve image entries and rejects a configured `campaign-site`, CMS
metadata, or additional schema entries. It is not automatically upgraded.

Version 2 is explicitly selected with `create --schema-version 2`. It requires
all twelve existing images plus `campaign-site`. Production images require a
registry tag and SHA-256 digest; test manifests may use immutable local image
IDs. Neither mode accepts floating images. The manifest also binds:

- The exact EmDash package version and npm integrity from the actual lockfile;
  that package integrity includes upstream migration code.
- The exact local patch inventory, lockfile, package/configuration files,
  editorial schema, local schema/identity/media installers, import-journal
  implementation, CMS recovery operator and campaign-site Dockerfile by SHA-256.
- The editorial schema version extracted from its source, operator-only
  migration mode, and explicit CMS image/migration/recovery release gates.
- The required CMS rollback boundary: matching SQL, media, encryption key and
  image, without discarding later Core orders. Recording this requirement does
  not prove the rollback implementation or authorize activation.

`verify` defaults to `--expected-schema-version 1`. Verifying a v2 manifest
requires `--expected-schema-version 2`; existing deployment callers therefore
remain closed to CMS releases until their migration/readiness paths are extended.
Checkout verification recomputes CMS identity and rejects missing/extra patches,
changed bytes, symlinked sources and malformed metadata. Compose comparison
includes the CMS image under v2 and still refuses it under v1.

`infra/emdash-spike/release.yml` replaces the campaign-site build with the
operator-supplied `LEONAID_CAMPAIGN_SITE_IMAGE`. Supply a reviewed registry
tag/digest for production, not an invented pin. The overlay alone neither
enables public routing nor performs migrations. Local source-build Compose is
not a complete release inventory: every required service must have an immutable
release image before a full manifest can be created.

Run `./leonaid test-emdash-spike --case release-manifest-compatibility` for the
v1/v2 contract suite. Both contracts also run in `./leonaid check`. These tests
use synthetic image references for structural positive/negative cases and real
repository source copies for byte-drift and symlink tests; they are not evidence
that a registry contains those fixture references or that a CMS release ran.

Still required: a complete built/published release inventory and provenance,
runtime schema/image checks, exclusive CMS migration, readiness/promotion,
upgrade and restore-based rollback with later Core order preservation.

## Embedded image identity

The campaign Dockerfile now generates `/app/cms-release-identity.json` in a
separate pinned Python build stage. Only the resulting non-secret metadata is
copied to the final Node image; Python and the source tree are not copied from
that stage. The source inventory also binds the identity generator/verifier.

`./leonaid test-emdash-spike --case release-image-identity` builds the actual
campaign image and reads its embedded metadata as the image's non-root user in
a read-only container with no network, no capabilities and no new privileges.
The checkout-side `cms_image_identity.py verify --root ...` reads metadata from
stdin and compares it to recomputed checkout identity. Changed schema/source
values and unknown fields are rejected with a fixed, sanitized message.

This proves the embedded CMS identity, not the entire release's provenance or
runtime database state. The build output remains in Docker's content-addressed
image/cache; no service, named network or host port is created. Operational
deployment/restore must still select the manifest-bound image, verify the v2
manifest against the same checkout, invoke this comparison before activation,
and verify database migrations and the complete recovery/key contract.

## Restore image preflight

Set `LEONAID_RESTORE_CMS_IMAGE` when restoring an EmDash topology with an image
candidate. `restore.sh` checks that candidate after backup validation but before
creating any target volume. `verify-cms-image.sh` resolves the local reference
once to an immutable image ID, extracts metadata using that ID in a read-only,
network-disabled container, and compares it to the checkout. It does not pull
images or mount restored data. Missing/mismatched identity fails closed.

A data-only restore without an image candidate remains supported and still
leaves all application activation closed. Supplying a valid image does not
change that rule. The recovery application rehearsal separately requires the
same preflight, replaces the CMS image reference with the verified immutable ID,
and checks the actual running container's `.Image` against that ID. Thus a tag
change after verification cannot silently select another CMS image for startup.

The live rehearsal also attempts the actual restore with an incompatible real
image, checks the specific preflight refusal and verifies that the target still
has no containers, volumes or networks. It then restores the same backup using
the matching candidate and completes the browser journey. This is not yet the
full production release-manifest, database-migration or upgrade/rollback gate.

## Read-only restored application schema check

`cms-recovery.mjs verify-application` checks the exact installed EmDash migration
name inventory, the local editorial schema contract and media binding guards,
constraints and columns, in addition to the existing campaign binding and
cross-database denial checks. Database inspection uses a repeatable-read,
read-only transaction with a bounded statement timeout. It never installs,
repairs or runs migrations. Pending or unknown upstream migration names are
rejected rather than accepted based on a migration count alone.

Restore invokes this check when an explicit CMS image candidate is supplied,
after SQL restoration and before returning to the still-closed application
activation boundary. Data-only restores retain the narrower `verify` contract.
The SQL recovery test proves six additional drift refusals, unchanged drifted
values after verification, and full source-row/sequence equality after each
fresh re-restore. This verifies the selected schema contracts and migration
ledger, not an arbitrary upstream physical-DDL audit or a successor upgrade.

## Closed-traffic editorial migration controller

`tools/pilot_release/migrate-cms.sh` takes the checkout root, explicit Compose
project, CMS image reference, one operation (`verify`, `upgrade-v1` or
`upgrade-v2`), and the deployment's ordered absolute Compose file paths. It adds
`infra/emdash-spike/migration-operator.yml` last. It uses `LEONAID_ENV_FILE` or
the checkout's `.env.local`; it never prints rendered configuration or secrets.

Before invoking an upgrade, the operator must obtain and verify the matching
CMS SQL/media/key/image recovery point and coordinate all external writers.
This controller does not yet automate that release/backup approval boundary.
Do not treat it as a complete deployment or rollback command.

The controller verifies the image's embedded identity against the checkout,
resolves it once to an immutable local image ID and requires the existing CMS
container to use that same image. This deliberately refuses an unreviewed older
runtime without the durable traffic gate. Selecting a successor EmDash binary
and proving rollback are separate, still-open gates.

An atomic, project-named Docker lock prevents concurrent controllers. A killed
controller's leftover lock requires explicit operator inspection; there is no
automatic lock stealing. The image-owned `close` operation creates an empty
0700 `cms-maintenance` directory in the shared bootstrap-state volume. All CMS
middleware requests except liveness then return non-cacheable 503 responses.
The controller stops only the CMS container to terminate requests that entered
before closure, then runs the selected one-shot migration. Core is not stopped.

The migration image runs non-root, read-only, without capabilities, and receives
only the CMS database credential and bootstrap volume on `cms-data`. It has no
Core/Twenty/order credential, storage credential, repository or Docker socket.
A pinned PostgreSQL session holds a separate nonblocking advisory lock across
preflight, the installer's transaction and final verification. Exact upstream
migration names and existing binding/media guards must match before editorial
DDL; no upstream package migration, implicit installation or repair is allowed.

Both success and failure leave CMS stopped and the durable gate closed. Even
an independent restart of the reviewed image cannot reopen traffic. There is
intentionally no automatic gate removal: activation remains subject to the
full release/recovery acceptance boundary. Backup manifests allow only this
optional empty 0700 directory alongside completed bootstrap state; links,
children, duplicate entries and different permissions are rejected. Restore
preserves the marker rather than interpreting a backup as permission to open.

`./leonaid test-emdash-spike --case migration-operator` runs the controller with
the actual built image, PostgreSQL and real Core in a fresh portless Docker
project. It proves mid-DDL rollback, competing-lock refusal, explicit v2-to-v3
upgrade, repeated verification/upgrade, content/draft/revision preservation,
and restart-resistant HTTP closure. Real Core identity/role checks and its SQL
probe remain available, including while the CMS migration lock is held.
Twenty/RustFS are intentionally absent in this focused proof; aggregate Core
dependency readiness and complete ordering are not claimed by this case.
