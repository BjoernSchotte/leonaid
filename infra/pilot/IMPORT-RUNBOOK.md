# Pilot import

The historic contact import is a one-time, dry-run-first migration.
The business Excel file determines the mapping; LeonAid provides no general
end-user importer for it. The original, personal reports, decisions and
approvals stay only under `.local/pilot/` or in an equally protected private
store.

## 1. Intake

```sh
./leonaid pilot-evidence-init
install -m 600 /geschuetzt/original.xlsx \
  .local/pilot/intake/historic-contacts.xlsx
```

Before any analysis, create
`.local/pilot/manifests/intake.json` with `schemaVersion: 1`:

```json
{
  "schemaVersion": 1,
  "sourceSha256": "<sha256>",
  "authorizationReference": "AUTH-PILOT-001",
  "purpose": "historic-sponsor-contact-import",
  "receivedAt": "2026-07-29T20:00:00Z",
  "responsibleActorId": "ACTOR-DATA-01",
  "externalEvidenceId": "EVID-IMPORT-001"
}
```

IDs are opaque. Names, email addresses and other source data do not belong
in the manifest.

## 2. Mapping by the coding agent

The coding agent analyzes the actual headers, sheets, formats, formulas,
required fields, empty columns, duplicates and character sets. It produces:

- a versioned mapping without personal data;
- a synthetic workbook with the same structure;
- damaged variants for missing headers, formulas, duplicate keys and
  invalid values;
- a stable source ID strategy. Row numbers and order are not IDs.

Uncertain or similar matches stay conflicts. The agent must not merge them
automatically.

## 3. Dry run

The target stack must already run from the approved manifest. Paths are
given relative to the repository, so that only the private `.local/pilot/`
store is mounted into the operator container:

```sh
./leonaid pilot-import dry-run \
  .local/pilot/intake/historic-contacts.xlsx \
  --env-file /etc/leonaid/staging.env \
  --batch-id IMPORT-PILOT-001 \
  --target-environment staging-club-111 \
  --manifest .local/pilot/manifests/intake.json \
  --mapping infra/twenty/import-mapping.json \
  --sheet Kontakte \
  --report .local/pilot/evidence/import-dry-run.json \
  --summary .local/pilot/evidence/import-summary.json
```

The private report contains per-row status, stable error codes and
candidates. The sanitized summary contains no rows or personal values.
Two dry runs against the same target state must be byte-identical.

## 4. Conflict resolution

Conflicts are resolved only in
`.local/pilot/manifests/resolutions.json`:

```json
{
  "schemaVersion": 1,
  "batchId": "IMPORT-PILOT-001",
  "decisions": [
    {
      "sourceId": "00000000-0000-4000-8000-000000000001",
      "decision": "use-existing",
      "targetTwentyId": "00000000-0000-4000-8000-000000000002",
      "decidedBy": "ACTOR-REVIEWER-01",
      "decidedAt": "2026-07-29T20:10:00Z"
    }
  ]
}
```

`create-new` is also possible and has no `targetTwentyId`.
`use-existing` accepts only an ID that the dry run reported as a candidate.

Then repeat the dry run with `--resolutions`. Its `planFingerprint` binds
source file, mapping, resolution, target environment, sheet and the full
current Twenty plan.

## 5. Recovery point and four-eyes approval

Before apply, a full cross-system recovery point of core, Twenty, Twenty
files and RustFS exists. The private approval object
`.local/pilot/manifests/approval.json` binds:

- batch and target environment;
- plan, source, mapping and resolution fingerprints;
- SHA-256 of the byte-exactly checked backup manifest;
- opaque recovery point ID;
- two different approval IDs and a timestamp with time zone.

A change to even one bound byte blocks apply.

## 6. Apply and verify

```sh
./leonaid pilot-import apply \
  .local/pilot/intake/historic-contacts.xlsx \
  --env-file /etc/leonaid/staging.env \
  --batch-id IMPORT-PILOT-001 \
  --target-environment staging-club-111 \
  --manifest .local/pilot/manifests/intake.json \
  --mapping infra/twenty/import-mapping.json \
  --resolutions .local/pilot/manifests/resolutions.json \
  --sheet Kontakte \
  --approval .local/pilot/manifests/approval.json \
  --backup-manifest .local/pilot/backups/manifest.json \
  --report .local/pilot/evidence/import-apply.json

./leonaid pilot-import verify \
  .local/pilot/intake/historic-contacts.xlsx \
  --env-file /etc/leonaid/staging.env \
  --batch-id IMPORT-PILOT-001 \
  --target-environment staging-club-111 \
  --manifest .local/pilot/manifests/intake.json \
  --mapping infra/twenty/import-mapping.json \
  --resolutions .local/pilot/manifests/resolutions.json \
  --sheet Kontakte \
  --backup-manifest .local/pilot/backups/manifest.json \
  --report .local/pilot/evidence/import-verify.json
```

Before the first write, apply runs the current dry run again and checks the
approval. An exclusive batch lock prevents parallel applies. Verify is green
only when no new, changed or unresolved records remain.

On a failure, no data is corrected manually. Operator and product owner
decide, based on the private report, between stop, a controlled retry or a
full restore.
