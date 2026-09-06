# Campaign schema lifecycle

`apps/campaign-site/src/campaign-schema.mjs` is the source-controlled version 1
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
- records version 1 in `options.leonaid:campaign_schema_version`;
- returns without schema/content updates when the existing contract matches.

Schema or version drift fails closed and remains untouched. Do not use a generic
`onConflict: update` import to repair incompatible installations. Future schema
versions need reviewed migrations, backup and rollback evidence. This metadata
comparison is not a complete physical PostgreSQL index/constraint audit.

## Evidence boundary

```sh
./leonaid test-emdash-spike --case schema-runtime
./leonaid test-emdash-spike --case campaign-runtime
```

The schema proof uses real EmDash migrations and PostgreSQL, three concurrent
installations, a persisted synthetic content row, repeated installation with
unchanged content/schema snapshots, and explicit field-rule/version drift.
The runtime regression exercises the same installer before real CMS/Core HTTP
operations. Both use collision-checked project-specific networks and volumes,
publish no host ports, and clean only owned resources.

This does not complete EMS-040: global action uniqueness, media fields,
generated TypeScript types and the complete `content-model` gate remain open.
Pilot/release operator wiring and upgrade/restore integration also remain open.
