# Campaign schema lifecycle

`apps/campaign-site/src/campaign-schema.mjs` is the source-controlled version 2
editorial collection definition. Its structure is exported with:

```sh
./leonaid export-campaign-schema
```

The JSON envelope contains `schema_version` and an EmDash-compatible `seed`.
Export is deterministic and reads only source code: the pinned Node container
has no network, environment credentials, database connection, live content or
repository-wide mount. This is a schema export, not a content backup.

The companion `auth/campaign-editorial.mjs` enforces stricter nested content and
aggregate limits than EmDash's field metadata supports. The exported seed alone
does not provide the complete LeonAid authorization or safe-content boundary;
deploy the matching application and validator, not a standalone imported seed.

## Installation

`installCampaignSchema(database)` is an operator-only helper. The runtime proof's
operator seed now calls it before importing synthetic content; no HTTP endpoint
or startup auto-migration calls it. Within a bounded PostgreSQL transaction it:

- serializes competing installers with a transaction-scoped advisory lock;
- creates an absent collection through the actual EmDash seed engine;
- checks existing field definitions, validation, defaults and relevant collection
  capabilities against the source contract;
- records version 2 in `options.leonaid:campaign_schema_version`;
- returns without schema/content updates when the existing contract matches.

Schema or version drift fails closed and remains untouched. Do not use a generic
`onConflict: update` import to repair incompatible installations. Future schema
versions need reviewed migrations, backup and rollback evidence. This metadata
comparison is not a complete physical PostgreSQL index/constraint audit.

### Explicit version-1 upgrade

The retained `campaignCollectionV1` is the exact legacy preflight contract.
`installCampaignSchema(database, { upgradeFromVersion1: true })` accepts only
that version and matching metadata. It adds nullable `hero_image` and
`social_image` fields and a nullable `partners[].logo`, using the actual EmDash
registry inside the same serialized PostgreSQL transaction. It advances the
version marker only with the complete schema change; ordinary installation
refuses version 1. There is no runtime auto-upgrade or generic drift repair.

The real `schema-migration` proof retains published content, an outstanding
draft and all revision rows byte-for-byte, rejects changed legacy rules, and
injects a PostgreSQL failure while adding the second image field. The first
field's DDL, repeater metadata and version marker all roll back. Three competing
explicit upgrades produce one upgrade and two unchanged results. Repetition
does not rewrite content or schema. Full backup/restore-based release rollback
remains the separate EMS-080 requirement; this is not downgrade support.

### Campaign image references

Version 2 allows only local PNG/JPEG/WebP references in the three named image
slots. Strings/URLs, remote providers, arbitrary metadata and dark variants are
not admitted. IDs have canonical ULID syntax; alt text and native cached facts
are bounded. Native provider enrichment adds nullable caption/placeholder facts
inside `meta`; those values must match the stored media row exactly.

`auth/campaign-media-references.mjs` resolves IDs through immutable action
ownership and ready status, locks media/binding rows in deterministic order, and
checks MIME, dimensions, SHA-256 presence, storage namespace and every supplied
cached fact. Same-user ownership of multiple campaigns is not permission to
reuse a media binding across them. System Admins follow the same binding rule.
Validation occurs before native normalization, creation, update, restore and
publication; resulting references are checked before commit. Content/revision
reads and comparisons also reject invalid references. A forged stored revision
is not trusted just because its parent belongs to the requesting actor.

These are application-level reference checks, not database triggers against a
trusted database owner. Media ready status does not grant anonymous delivery.
Native picker context, browser image previews, full image-field UX and public
publication/reference-gated delivery still require their separate proofs.

## Campaign binding constraints

After collection installation, the operator must call `installCampaignBindings`.
The binding contract is version 2 (`options.leonaid:campaign_binding_version`),
separate from the editorial collection version. It installs the immutable
content/revision binding triggers plus the physical PostgreSQL constraint
`leonaid_campaign_action_unique UNIQUE (action_id)`.

The constraint is immediate and covers every row, including soft-deleted content
and all locales. A different CMS slug or language cannot create a second page
for the same Core action. It also protects direct database writes outside the
application's per-action creation lock. Permanent deletion remains a separately
controlled operation; this constraint does not retain tombstones after a row
has physically ceased to exist.

Installation locks both content and revision tables in a bounded transaction,
rejects invalid or duplicate existing bindings without changing content, and
records the binding version only after successful installation. Existing
pre-versioned guards can be upgraded only when their definitions match and the
data is unique. Versioned installations are check-only on repetition; missing
or changed constraints are not silently repaired. Conflicting legacy rows need
an explicit reviewed resolution, not automatic deletion or reassignment.

Runtime checks verify the exact unique key and its valid, ready, immediate,
non-partial backing index as well as the existing trigger definitions and binding
version. A missing, deferred or composite substitute is rejected. These checks
protect application invariants, not a sandbox against the trusted database owner.
The EmDash seed alone does not install these PostgreSQL constraints: deploying
only the seed is insufficient even though the editorial schema is unchanged.

## Generated field types

```sh
./leonaid export-campaign-types
```

This command prints deterministic TypeScript from the same source collection;
it never writes the checkout. Review and apply its output to
`apps/campaign-site/src/campaign-fields.generated.ts` when changing the schema.
The pinned Node container has no network and mounts the checkout read-only.
The generator reads schema source, not credentials, content or a live database.
No development server, HTTP typegen endpoint, CMS token or new dependency is
required. This is LeonAid's build-time field generator, not EmDash's dev-server
module augmentation.

The generated interface describes stored field shapes, including absent/null
optional values, nested repeaters and the closed theme union. It does not make
an arbitrary CMS record safe to render: runtime authorization, immutable binding
checks and the stricter `campaignEditorial` validation remain mandatory. Core
UUID validity, text lengths and link safety cannot be inferred from TypeScript
string types. Content IDs, revision metadata and operational Core data are not
part of this field-only interface.

`./leonaid check` rejects stale generated output and compiles actual positive and
negative consumer fixtures. The real PostgreSQL schema proof generates the same
types from `SchemaRegistry.getCollectionWithFields()` after installation and
checks exact equality with both the source-generated and committed output.
Collection field ordering does not change the output; unsupported field types
fail explicitly instead of silently widening to `any` or `unknown`. New media
fields now use a bounded local `CampaignImageReference` shape; TypeScript still
cannot prove the referenced row belongs to a campaign or is ready.

## Evidence boundary

```sh
./leonaid test-emdash-spike --case schema-runtime
./leonaid test-emdash-spike --case schema-migration
./leonaid test-emdash-spike --case campaign-media-http
./leonaid test-emdash-spike --case campaign-runtime
```

The schema proof uses real EmDash migrations and PostgreSQL, three concurrent
installations, a persisted synthetic content row, repeated installation with
unchanged content/schema snapshots, and explicit field-rule/version drift.
The runtime regression exercises the same installer before real CMS/Core HTTP
operations. Both use collision-checked project-specific networks and volumes,
publish no host ports, and clean only owned resources.

This does not complete EMS-040: native image-field UX and the complete
`content-model` gate remain open.
Pilot/release operator wiring and upgrade/restore integration also remain open.
