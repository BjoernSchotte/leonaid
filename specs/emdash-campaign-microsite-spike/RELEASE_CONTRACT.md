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
