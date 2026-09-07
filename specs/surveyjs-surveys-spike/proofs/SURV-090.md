# SURV-090 — Deletion, recovery and operational limits

Status: **in progress**. Own license remains **UNDEFINED**. This proof accepts
090.A2 / 090.S2 only. It does not accept the complete work package or task 090.1.

## Durable erasure and process-crash recovery

Source revision: `8432163` (the unchanged implementation and probe content that
passed the run below, committed after execution). Runtime pins are recorded in
`infra/locks/images.env` and the Dockerfiles used by the harness. Python uses the
pinned UV Python 3.13 image; PostgreSQL 16.9 and RustFS 1.0.0-beta.11 are the actual
persistence services. This test uses only synthetic data.

Command, from the checkout root:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" deletion
```

Successful isolated project: `leonaid-surveys-833458328-86796`; command exit **0**.
The harness selected seven unused subnets, published no host ports, removed its
containers/networks/volumes and verified that no project containers or volumes
remained. The Chromium foundation journey passed (one case, 1.2 seconds). This
browser check proves the existing member/public foundation only; it is **not**
delete-button E2E acceptance.

### Implemented behavior

- `POST /api/v1/surveys/{survey_id}/delete-permanently` requires an authenticated
  actor with the existing delete capability, a trashed survey and its current
  revision. It atomically commits an erasure record and an empty-payload outbox
  event. The response is `no-store` and contains only identity, status and times.
- The erasure record retains opaque survey/actor/event IDs, an operation-ID hash,
  revision and timestamps. It stores no definition, title, answer, recipient,
  credential or plaintext operation ID. An active original requester can replay
  the exact operation to observe completion after the survey row is gone.
- Once intent is committed, authoring/restoration and re-creation of the same
  survey ID are refused. A database trigger independently prevents inserting or
  updating that survey ID. Inactivity does not request erasure.
- The durable worker takes the same survey advisory/row locks as export and
  authoring operations. It removes exact recorded object versions and checks each
  export's deterministic key for an upload that crashed before its DB commit.
  Only after storage succeeds does it remove export jobs and the survey's
  relational content. The completed content-free record remains.
- A storage exception leaves the intent and database references available for
  retry. Provider diagnostics are replaced by the generic
  `survey_deletion_failed` error. A late export event with no remaining job does
  nothing, including when deletion wins after its initial identity lookup.

### Named assertions and results

`tools/surveys/deletion_live.py` runs these stages through the real API, outbox,
PostgreSQL and RustFS adapters:

1. **prepare:** unauthenticated, non-trash and stale-revision deletion requests
   are rejected; rejected requests create no erasure record. A fixture includes
   published definitions, populated completed responses, a recipient invitation
   and an aggregate snapshot. Two real CSV exports are produced: one committed
   normally and one uploaded through the production renderer/storage path before
   an injected exception rolls back its database transaction. Both exact file
   versions exist before deletion.
2. **prepare:** the valid request commits one pending record; exact replay returns
   the same result and another operation ID conflicts. Restore and downloads are
   denied. The ledger's exact column allowlist and hashed operation ID are
   inspected; seeded sensitive text is absent from the ledger.
3. **crash:** claim the exact deletion event and execute a real S3 version DELETE.
   Verify that the version is absent, then terminate the worker process with
   `os._exit(73)` before its database transaction commits. The harness requires
   exactly that exit code.
4. **recover:** verify the durable event is still processing on attempt 1, the
   intent is incomplete, both export-job records remain, and exactly one of the
   two original file versions is now absent. Advance this synthetic event's
   claim timestamp beyond the production lease and let the real queue reclaim
   it. Attempt 2 completes successfully.
5. **recover:** assert zero targeted rows in `survey`, `survey_draft`,
   `survey_version`, `survey_participation`, `survey_operation`,
   `survey_invitation`, `survey_grant`, `survey_analysis_snapshot` and
   `survey_export_job`; both exact versions and their current keys are absent.
   The grant table is checked for absence but this fixture does not seed a grant.
6. **recover:** exact API replay reports completion; API reads/recreation fail,
   and direct SQL recreation hits the erasure guard. Releasing the delayed
   export event completes harmlessly without recreating a job.

Sanitized result: [SURV-090-deletion.json](assets/SURV-090-deletion.json).
No raw temporary state, credentials, answer payloads or unrestricted logs are
included in the retained artifact.

The first run (`leonaid-surveys-833458328-86337`) failed in the probe's ledger
column assertion: iterating an asyncpg Record yields values, not column names.
The assertion was corrected to `ledger.keys()` after that process terminated.
The successful fresh-stack run above exercised the corrected probe. Production
code was unchanged between those two runs.

Additional successful checks: scoped Ruff check and MyPy for the new adapter,
authoring repository, HTTP transport and worker composition; OpenAPI/client
regeneration; `bun run --cwd apps/web typecheck`; `git diff --cached --check`.
These checks do not replace the live erasure assertions.

## Acceptance ledger

| Item | Result | Evidence / remaining work |
| --- | --- | --- |
| 090.A2 / 090.S2 | Passed | Actual version deletion, process termination, lease reclaim and complete relational/object cleanup above. |
| 090.1 | Open | Durable erasure backend delivered; configurable retention and backend UI still required. |
| 090.2 / 090.A3 | Open | Content-free ledger exists; separate preservation and reapplication across a real backup restore are not implemented/proven. |
| 090.3 / 090.A4 | Open | Full limits and log-marker acceptance remains. |
| 090.A1 | Open | A late export is covered; full concurrent autosave/completion/export/deletion interleavings remain. |
| 090.T1 | Open | A2 subset passed; remaining integration criteria are not waived. |
| 090.T2 / 090.A5 | Open | Required open-browser trash/save/recovery and backend deletion UI journeys remain. |

Operational boundaries: this proof keeps one configured object-storage bucket.
A historical bucket migration or externally created extra object versions is
not covered. The schema downgrade deliberately refuses to discard the deletion
ledger; the backup/recovery work must preserve and reapply it. Retry exhaustion
uses the existing durable outbox's dead-letter handling; user-facing status and
retry controls still need the module integration. No complete retention or
backup-restoration claim is made here.
