# SURV-090 — Deletion, recovery and operational limits

Status: **in progress**. Own license remains **UNDEFINED**. 090.A2 / 090.S2 are accepted. The retention section adds proven behavior for
090.1 and the inactivity-preservation part of 090.A3. The complete work package
and task 090.1 remain open. The recovery section proves checkpoint reapplication
after an actual DB/object restore; full operator integration remains open.

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
| 090.1 | Open | Durable erasure and configurable retention (including settings UI) delivered; manual deletion/status UI and full A1/A5 acceptance remain. |
| 090.2 / 090.A3 | Open | Authenticated checkpoints and real DB/object restore reapplication are proven below; independent source-loss continuity and existing Restic/operator integration remain open. |
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


## Configurable retention and member-backend acceptance

Source revision: `c27e2d9` (unchanged source/probe content committed after the
successful executions). Decisions are recorded in
[DECISIONS.md](../DECISIONS.md#retention-scheduling-semantics). Own license stays
**UNDEFINED**; no dependency was added.

Commands from the checkout root:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" retention
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" deletion
```

- Retention run: `leonaid-surveys-833458328-91543`, exit **0**; two Chromium
  journeys passed in 3.7 seconds, including the mobile settings journey.
- Shared-deletion regression: `leonaid-surveys-833458328-92130`, exit **0**;
  actual object DELETE, exit 73, reclaimed attempt 2 and all original cleanup
  assertions passed; foundation Chromium journey passed in 2.0 seconds.
- Both runs used distinct allocated subnets, no published host ports and fresh
  volumes. The harness removed its resources and verified no remaining project
  containers/volumes. No other worktree's resources were changed.

### Proven assertions

- [x] **Policy integration:** `retention_live.py prepare` verifies both settings
  default to null, unauthorised members receive 403, zero/negative/over-limit
  periods receive 422 without mutation, stale revisions receive 409 and exact
  operation replay is idempotent. Updating only the inactivity timeout preserves
  omitted retention fields; explicit null disables each stage independently.
- [x] **Lifecycle integration:** the real sweep moves old ended and archived
  surveys into trash with an explicit one-second policy, while disabled trash
  retention creates no deletion record. A busy advisory lock is skipped within
  the five-second assertion bound; the next sweep handles that survey. Restore
  starts a new retention clock; archive/unarchive preserve it. These assertions
  use actual PostgreSQL state and synthetic timestamp advancement.
- [x] **Inactivity separation:** an active survey's 90-day-old in-progress answer
  becomes partial but its seeded answer remains identical. With automatic
  retention disabled all five fixture surveys remain. After retention runs,
  the active survey and draft still exist; respondent inactivity never selected
  them for deletion.
- [x] **Worker integration:** after `prepare` enables one-second trash retention,
  the harness starts the real production worker process. `recover` waits at most
  60 seconds and verifies two due surveys were erased, their deletion records
  completed and exactly one completed erasure event exists per survey. No direct
  sweep invocation or hand-written queue claim substitutes for this phase.
- [x] **Backend E2E:** `surveys-retention.spec.mjs` opens mobile navigation as the
  admin, sets 30/7 days in the real module, saves, and checks API persistence as
  2,592,000/604,800 seconds. Reload retains both values. Clearing and saving both
  fields persists nulls. A non-admin opens the supported survey-module route,
  cannot see the settings, and gets 403 from their API. API responses are no-store.
- [x] **Visual observation:** the retained 390-pixel mobile form was manually
  inspected: labels, explanatory text and save control are readable and the
  automated horizontal-overflow assertion passes. This is a review of the new
  settings form, not a complete application visual/accessibility certification.

Artifacts: [integration results](assets/SURV-090-retention.json),
[browser results](assets/SURV-090-retention-browser.json),
[mobile form](assets/SURV-090-retention-mobile.png).
Private test sessions and raw traces were not copied into these artifacts.

Ruff checks passed for the affected Python files; MyPy passed for the retention,
delete and authoring adapters plus HTTP/worker entrypoints; web TypeScript checking
and OpenAPI/client generation passed. The full live runtime also verifies the
worker import after the correction described below.

### Failed attempts and corrections

- `...-89816` failed at worker startup because `asyncpg.Pool[Any]` was evaluated
  at import time. A separate container import reproduced the exception. Adding
  postponed annotation evaluation fixed the production module.
- `...-90161` passed API/production-worker checks, then the browser probe failed
  because it had not opened mobile navigation. The probe was corrected.
- `...-90841` additionally passed the admin's complete mobile settings journey,
  then used the wrong starting page for an ordinary member. The general admin
  landing page redirects that persona to the PWA by design; the survey module
  remains accessible at `/admin/surveys`. Using that supported entry fixed the
  probe without adding rights or changing production access policy.
- Each failed process was confirmed terminal before edits and a fresh isolated
  run was started. The final successful run above covers all corrected assertions.

### Remaining scope

This accepts the configurable-retention portion of 090.1 and proves that
inactivity alone deletes nothing. **090.A3 remains open** because it also requires
real backup restoration and deletion-record reapplication. Full autosave,
completion and erasure interleavings, log/limit acceptance, manual erasure/status
controls and the open-respondent deletion E2E journey are still required.
The migration's backfill of already closed rows has not yet received a dedicated
upgrade-fixture proof; the runs above prove migration from empty volumes and
post-migration lifecycle clocks. Real operational retention periods remain a
separate deployment decision.


## Offline erasure reapplication after an actual backup restore

Implementation revision: `875221c`. The live run used its checkpoint/reapply
behavior; the final shared 32 MiB export/import boundary guard was added after
that run and independently covered by the unit boundary test. No backup, restore,
erasure, authentication or access behavior changed after the live run.

Command:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" recovery
```

Successful final project: `leonaid-surveys-833458328-96383`, exit **0**. An earlier
run, `leonaid-surveys-833458328-95232`, also passed the initial restore/reapply
probe; the final run additionally exercises the actual checkpoint-export CLI,
mode 600 and old-session/public-route access after restart. Both projects used
fresh isolated resources and no published host ports. Containers, networks and
volumes were removed; the harness verified no remaining project containers or
volumes. The foundation Chromium journey passed after application restart.

The test restores a real custom-format PostgreSQL dump with `pg_restore
--exit-on-error` and a real archive of the stopped RustFS volume. It replaces only
the fresh test project's data. It does **not** invoke the existing Restic wrapper
or simulate loss of the machine that holds the latest checkpoint.

### Proven assertions

- [x] **Backup predates deletion:** `recovery_live.py seed` creates a published
  survey, a populated response, a frozen analysis selection and an actual CSV
  export through the production outbox/storage adapters. With survey writers and
  RustFS stopped, the harness captures the database and complete object volume.
- [x] **Newer deletion record:** after the backup, the real API trashes and
  permanently deletes the survey. The worker removes its row and exact file
  version. The checkpoint export includes this newer deletion and no seeded
  answer text. The CLI writes the authenticated file atomically with mode 600.
- [x] **Actual resurrection while offline:** after restoring both artifacts,
  `restored` verifies the survey is active, its deletion record is absent and the
  original exact object version exists with the original SHA-256 and answer text.
  API, public surface, proxy and worker remain stopped at this stage.
- [x] **Tamper rejection before mutation:** a checkpoint with its record removed
  but its old authentication value exits 1 with a generic diagnostic. A second
  inspection confirms the restored survey/object state is still unchanged.
- [x] **Reapplication and repeat:** the authenticated checkpoint passes the
  installation/cutoff checks, commits erasure intent and removes the restored
  survey, response, snapshot/export relations and exact file through the existing
  eraser. The CLI runs twice successfully. A checkpoint that omits a deletion
  already known by the database is rejected by the adapter.
- [x] **Access after restart:** the application starts only after successful
  reapplication. The old authenticated session gets 404 for survey and export
  download; the public definition route also returns 404. The deleted data is
  not recovered through the old session.

Sanitized results: [SURV-090-recovery.json](assets/SURV-090-recovery.json).
Actual database dumps, RustFS archives, checkpoint identities/authentication
values and test-session credentials are not included in the committed artifact.

`tests/unit/test_survey_recovery.py`: **12 passed** (0.07 seconds, exit 0), covering
roundtrip field allowlisting, record removal/alteration, unexpected answer fields,
wrong signature/key/installation, stale/naive/future cutoffs, duplicate identities
and the exact shared document-size boundary. MyPy passed for the application
contract and both adapters. Scoped Ruff checks and `git diff --check` passed on the final source.

### Acceptance boundary

This is evidence for 090.2 and 090.A3, not full acceptance of either. The current
implementation is an offline primitive whose caller must keep application writers
stopped. [RECOVERY.md](../RECOVERY.md) specifies the implemented contract and
remaining requirements. The existing `tools/backup/restore.sh` does not yet invoke
it automatically. Independently retaining the newest checkpoint across source
loss, proving the operator-selected freshness cutoff and covering the existing
Restic/fresh-target/rotation workflow remain open. Do not use this result to claim
complete production disaster recovery or close SURV-090.
