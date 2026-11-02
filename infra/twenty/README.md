# Twenty contract for LeonAid

## Binding baseline

LeonAid provisions only the subset of the Twenty API declared in
[`schema.json`](./schema.json). Verified:

- Twenty `2.54.0`, upstream tag `twenty/v2.54.0`
  (`c75ef7bfd0589219bd22e8f134df458af0af3445`)
- Container digest
  `sha256:e64479a4daa9211864eb45ffdf15ce7a44a3664850dab06213105027538fce1e`
- GraphQL Metadata API at `/metadata`
- REST Metadata API at `/rest/metadata`
- Generated REST Data API at `/rest/<objectPlural>`

A Twenty upgrade is a deliberate contract change. Before the merge, the pin,
the manifest and `tools/twenty/test.sh` must be updated together and proven
against an empty instance.

The production Data API contract is documented separately in the
[`Twenty CRM Gateway`](../../src/leonaid/adapters/twenty/README.md)
and is checked for real by `./leonaid test-twenty-gateway`.

## One-time contact import

Twenty 2.54.0 can import CSV, XLSX and XLS files through its interface, but
only for one object at a time. For the PoC, LeonAid deliberately uses its own
API import path, because it needs the business primary keys, a verifiable dry
run and a shared row-level report for companies and people. The path stays on
Twenty's supported Data API and does not access internal tables.

The versioned
[golden workbook](../../tests/fixtures/golden/v1/outputs/019f9a37-b6da-7521-b590-ec1e8215a6bf/leonaid-crm-import.xlsx)
and [`import-mapping.json`](./import-mapping.json) are the template for a
real existing-data file. The first row must contain exactly these columns:

```text
source_id, record_type, company_name, given_name, family_name, email,
street_line_1, postal_code, city, country
```

- `source_id` is a stable UUIDv4 per row and makes reports comparable across
  repeated runs.
- `record_type` is `COMPANY` or `PERSON`.
- Companies need `company_name`; people need `given_name` and `family_name`.
- Empty cells never delete existing CRM values.
- Company names are compared independent of Unicode form, case, whitespace
  and punctuation. Without a company, given name plus family name is the
  match key.
- No match is reported as `new`, exactly one match as `update` or
  `unchanged`, several matches as `conflict` and invalid rows as `rejected`.
- Conflicts and rejected rows are never written automatically.

Put the working file in the repository or in the ignored directory
`.local/`. Before the first run:

```sh
./leonaid provision-twenty
./leonaid import-crm dry-run .local/contacts.xlsx \
  --report .local/import-dry-run.json
```

The JSON report has file mode `0600` and lists, for each Excel/CSV row,
status, reason, match candidates and the affected Twenty ID. Only after a
business review is the same state applied:

```sh
./leonaid import-crm apply .local/contacts.xlsx \
  --report .local/import-apply.json
```

A repeated dry run must then show only `unchanged`, deliberately unresolved
`conflict` cases or `rejected` rows. Existing companies are not renamed;
non-empty address fields and, for people, email and company relation are
added or updated in a controlled way.

References for the native Twenty import:

- [Import overview](https://docs.twenty.com/user-guide/data-migration/overview)
- [Supported file formats](https://docs.twenty.com/user-guide/data-migration/capabilities/file-formats)
- [Update existing records](https://docs.twenty.com/user-guide/data-migration/how-tos/update-existing-records-via-import)

## Business boundary

Twenty stays the system of record for companies, people, contact channels and
general CRM activities. LeonAid Core stays the system of record for charity
actions, action-specific roles, assignment history, orders and invoices.

For the charity admin spike, two custom objects are mirrored and clearly
described as read models:

- `charityAction`: period, lifecycle, target and archive slug
- `acquisitionAssignment`: acquirer, status, follow-up date and relations to
  the action and to either a company or a person

The stable `leonaidId` fields connect both systems. Changes in Twenty must not
bypass the business invariants of the core.

## Declaratively managed capabilities

The manifest describes and the provisioner checks:

- two custom objects with text, number, date/time and select fields,
- three `MANY_TO_ONE` relations and the inverse fields Twenty creates,
- two table views for charity admins with explicit visible columns,
- the user role `LeonAid Charity-Admin`,
- the technical role `LeonAid Integration`,
- exactly one API key assigned to this technical role.

Provisioning uses only supported metadata mutations:

- `createOneObject`
- `createOneField`
- `createView`, `createViewField`, `updateViewField`
- `createOneRole`
- `upsertObjectPermissions`, `upsertFieldPermissions`,
  `upsertPermissionFlags`
- `createApiKey`, `generateApiKeyToken`

Internal Twenty tables are neither read nor changed.

## Match keys on standard objects

`standardObjects` in the manifest declares LeonAid-managed scalar fields on
Twenty's built-in objects. The provisioner creates missing fields with
`createOneField`, verifies them for drift like custom-object fields and
includes them in the snapshot; it never changes other standard fields.

Companies and people receive the text field `leonaidMatchKey`. It holds the
normalized name (`normalize_match_name`: case, Unicode, umlaut, punctuation and
`K.G.`/`e.K.` folding) that public orders, sponsor capture and imports use to
detect an existing party. The integration role may read and update it. Core
sets it on every create and name change, and request paths look parties up
with an exact `leonaidMatchKey[eq]` filter instead of listing all records.
`provision.py verify-key` proves that the integration key can write the field
and filter by it.

Records created or renamed outside LeonAid (Twenty UI, native CSV import,
installations from before this field existed) have no or a stale key. Such a
record is still found when its name contains the searched word literally, but
spelling variants (for example `Müller`/`Mueller`) need the stored key:

```sh
./leonaid repair-crm-match-keys                       # full, idempotent run
./leonaid repair-crm-match-keys --changed-within 30   # recent changes only
```

`./leonaid provision-twenty` runs the full repair after provisioning. On an
existing installation, run the full repair once after the schema update, and
again after bulk imports or edits in the Twenty UI. The command uses at most
60 Twenty requests per minute by default (`--requests-per-minute`) so the live
system keeps headroom in Twenty's shared quota.

## Least-privilege key

`LeonAid Integration` may only read and update, in a controlled way,
companies, people, charity actions and acquisition assignments. The role has:

- no global read, write or delete permissions,
- no settings, role, data model, workflow, import, export or tool flags,
- no soft-delete or destroy permissions,
- explicit field allowlists.

Twenty models field permissions as restrictions. Relation field permissions
must be identical on both sides; therefore the required inverse relations are
also allowed. `position`, `createdBy` and `updatedBy` need write permission on
record create, even though Twenty sets their values server-side. These
technically required permissions are visible in the manifest.

With the generated key, the contract test proves:

1. Company create and reads of both LeonAid objects work.
2. Company fields that are not allowed are not returned.
3. Opportunities are denied with `PERMISSION_DENIED`.
4. Administrative role metadata is denied.

The token is stored only once in the ignored file
`.local/twenty/integration.env` with file mode `0600`. It is never written to
logs, snapshots or Git.

## Operations and drift

```sh
./leonaid provision-twenty
```

The command:

1. starts the pinned Twenty instance,
2. creates missing declared objects,
3. reconciles the technically required permissions,
4. aborts with an exact path on any differing managed object, field,
   relation, view, role or API key property,
5. writes a secret-free canonical snapshot to
   `.local/twenty/schema-snapshot.json`.

Existing drift is never silently hidden by renaming or deleting. An intended
change needs an updated manifest, a deliberate migration and the full contract
test.

## Verified limits of Twenty 2.54.0

- Custom fields cannot be marked as mandatory in the product. Required-field
  rules therefore stay in LeonAid Core.
- The relation API used here supports `MANY_TO_ONE` and `ONE_TO_MANY`. The PoC
  uses no many-to-many lab feature.
- Object and field permissions do not replace action-specific row-level
  authorization. Acquirers access data only through LeonAid Core.
- Charity admins with direct Twenty access see all records within the allowed
  objects. The assignment to self-managed actions is still checked
  server-side in the core.
- The API is designed for 100 requests per minute and batches of at most 60
  records. POC-031 must implement pagination, backoff and batching within
  these limits.
- Workflows, webhooks and Twenty mail delivery are not part of POC-030.
- Since 2.54 views have no `isCustom` field; a LeonAid view is identified by
  its fixed id from `schema.json`.
- Since 2.54 Twenty builds indexes and validates foreign keys of a schema
  change in deferred worker jobs and refuses further schema mutations of the
  workspace ("deferred schema action(s) are still running") until they
  finish. The refusal happens before any change; the provisioning client
  (`tools/seed/golden.py`) repeats the request for up to 180 seconds.

References:

- [Twenty APIs](https://docs.twenty.com/developers/extend/api)
- [Twenty Custom Objects](https://docs.twenty.com/developers/contribute/capabilities/backend-development/custom-objects)
- [Twenty v2.54.0 source](https://github.com/twentyhq/twenty/tree/twenty/v2.54.0)

## Real verification

```sh
./tools/twenty/test.sh
./leonaid test-twenty-gateway
./leonaid test-crm-import
```

The schema test starts Twenty from empty volumes, provisions twice, compares
canonical snapshots byte for byte, checks the real integration key and then
changes a field through `updateOneField`. `check` must report the concrete
field path including the actual value.

The import test starts its own empty Twenty, provisions and fills it through
the public APIs, runs dry run, initial import, targeted update and identical
repeat, and verifies reports and records again through the production CRM
gateway.
