# SURV-030 — Lifecycle and version evidence

Date: 2026-09-06. Status: partial. Member lifecycle UI, baseline migration and
scheduled closure evidence are recorded below. Permanent deletion is still open
in SURV-090 and prevents claiming every edge of PLAN section 5 is accepted.

## Implementation

The real API now exposes a protected survey summary, revisioned lifecycle
commands (end, archive, unarchive, trash, restore) and idempotent duplication.
Survey lifecycle revision is separate from draft revision. Each lifecycle write
locks the same survey row as response saves/completion and publication. The
transaction that obtains the row first determines the close/submit ordering;
a write after closure cannot bypass it with an old revision or operation key.

Ending or trashing an active survey records the server cutoff and classifies
open participations as partial. A stored partial marker remains partial on read;
only a successfully accepted changed answer can resume it while access is open.
Completed responses remain completed. Trash timestamps are cleared on restore.
A published survey restores to ended; an unpublished survey restores to draft.
Neither archive restoration nor trash restoration opens public participation.

Duplication copies the latest immutable published questionnaire when present,
otherwise the draft. It creates a standalone draft owned by the requesting
member, with new identity, no publication, no participation/resume credentials,
no explicit grants and no action association. Existing questionnaire IDs remain
stable. Invitations are not implemented yet; duplication does not create them.
The generated OpenAPI and TypeScript client include the new routes.

## Live verification

`./leonaid test-surveys-lifecycle` rebuilt the current source in isolated Compose
project `leonaid-surveys-833458328-24940`, with fresh volumes, explicit unused
subnets and no published host ports. Migration, real API/PostgreSQL foundation,
existing response contracts and the lifecycle contract passed. The member/public
Chromium infrastructure test passed in 1.1 seconds; it is not lifecycle UI proof.

`tools/surveys/lifecycle.py` verifies through real HTTP and SQL:

- All 25 status/action combinations: permitted transitions succeed; forbidden
  transitions reject without changing the summary. Also covers the distinct
  unpublished trash → draft restoration edge.
- Two simultaneous draft saves at one revision yield exactly one success and
  one conflict. Publication contains the winning draft, not a lost/stale edit.
- Existing participations restore their original immutable version after v2;
  new participations bind v2. Two simultaneous publications at one revision
  yield one success and one conflict, with exactly three total versions.
- Concurrent end/complete produces either a completed response accepted before
  closure, or a rejected completion and partial response. Subsequent writes and
  public access fail. Repeating the end operation returns its original result.
- Ended drafts reject edits. Archive/trash/restore keeps access closed.
- Duplicate retries return the same new draft. SQL verifies the copied published
  definition and absence of participations, versions, grants and action linkage.
- Unauthenticated metadata access is rejected. The synthetic fixture rows are
  deleted by the contract's finally block.

Strict mypy passed for the adapter/transport, four domain tests passed, source
lint passed and the regenerated API client passed TypeScript checking.

## Remaining boundaries

030.A1 still requires the migration path over an existing baseline fixture;
this run proves fresh migration only. 030.A4 requires the member lifecycle UI
from SURV-060. Full persona/permission coverage, automatic scheduled closure,
retention/permanent deletion and invitations remain their respective later work.
No work package or entire spike completion is claimed by this evidence.

## Member lifecycle UI acceptance

The later [SURV-060 evidence](SURV-060.md) closes the earlier 030.A4 gap and
030.T2: `./leonaid test-surveys-lifecycle` ran successfully as
`leonaid-surveys-833458328-88804` against the real member/public hosts, API and
PostgreSQL. `member manages lifecycle and timeout through the real module`
created, published, ended, archived, trashed and restored a survey through the
UI at 1440 × 1000. Reload and an independent SQL verification retained ended
state; the public endpoint rejected access and the start control stayed absent.
The command also reran the existing lifecycle/race contract and verified its
isolated teardown. The proof includes the synthetic rendered lifecycle state.
030.S4 is reconciled to this named test. Baseline-upgrade acceptance 030.A1 and
the remaining broader permission/retention work stay open.

## Existing-data migration proof

`./leonaid test-surveys-migrations` completed with exit code 0 in isolated project
`surveys-migrations-833458328-92030`. It used the pinned PostgreSQL 16.9 image
and core image built from the working source, an internal network, a dedicated
volume, two synthetic databases and no published host ports. Own resources were
removed successfully. The current task adds this dedicated command to `leonaid`.

`tools/surveys/migrations.py` and `migrations.sh` cover:

- Empty database → `0028_survey_timeouts`, then repeat `upgrade head`.
- Existing `v0.sql` fixture loaded at `0011_public_orders`, upgraded to baseline
  `0026_invoice_payment_snapshot`, then through both survey migrations to head.
- Row counts and SHA-256 fingerprints for all 46 pre-existing base tables match
  before/after the survey migrations and again after rolled-back constraint tests.
  Invoice and commitment fixtures must contain rows; this is not an empty baseline.
- Twelve schema/status checks, including immutable publication, survey-bound
  version foreign keys, lifecycle/timestamp consistency, bounded timeouts,
  singleton settings and effective partial classification without answer loss.
  Deferred foreign keys are explicitly forced before asserting rejection.

The first harness run (`...91925`) failed because the test did not initially
force the deferred publication foreign key. The corrected harness passed as
`...92030`; no product constraint was relaxed. Sanitized assertion reports:
[empty](assets/SURV-030-migration-empty.json) and
[upgrade](assets/SURV-030-migration-upgrade.json). `preexistingDataPreserved=false`
in the empty report means there was no legacy baseline to compare; the upgrade
report asserts preservation explicitly. These reports contain no respondent data.

This closes the migration evidence gap within 030.A1. Scheduled closure and the
remaining lifecycle acceptance must be reconciled separately before checking
that whole criterion or work package.

## Scheduled closure through the backend and worker

The protected `PUT /api/v1/surveys/{id}/schedule` accepts a future timestamp with
an explicit timezone, or null to remove a deadline while editing remains open.
It requires publish capability and the survey revision. Replays return the
original response; stale revisions and reused keys with different content fail.
Datetime input is normalized to UTC. The member UI displays local time and its
zone, persists through the generated API client and reloads the actual summary.

Public writes enforce the deadline even with the worker stopped. An expired
active survey cannot be reopened by clearing its deadline. An expired draft may
change its schedule, but cannot publish until the deadline is removed or moved.
The worker closes due active surveys in batches of 100 using survey-first row
locks with SKIP LOCKED, then classifies participation inactivity. Its normal
sweep interval is five seconds, reduced to 250 ms after a full batch. Closing
increments the survey revision once and marks in-progress participations partial;
answer contents, participation revisions and completed responses are preserved.
The administrative summary may show active during worker lag; public writes
already reject at the cutoff. No claim of instantaneous summary propagation.

`./leonaid test-surveys-lifecycle` completed with exit 0 in
`leonaid-surveys-833458328-94822`, rebuilding this working source. The integration
script `tools/surveys/schedule.py` uses a genuinely stopped/restarted worker and
DB time injection to verify validation, stale/replayed requests, expired draft
publication, rejected late start/save/completion, rejected reopening, durable
closure after restart and no repeated revision increment on a later sweep.
Pending and completed answer snapshots are checked directly in PostgreSQL.

The same run passed all 25 lifecycle/action combinations, publication/edit and
close/completion races, immutable version binding and duplication checks. All
three Chromium tests passed in 5.4 seconds. The member test in
`tests/e2e/surveys-module.spec.mjs` additionally sets a future end via the UI,
checks the server timestamp, reloads the field, clears it and verifies persisted
null before continuing the complete manual lifecycle journey. Browser timezone
was explicitly UTC; DST ambiguity and additional timezone UI coverage remain
unclaimed. The project used unused explicit subnets, no published host ports,
fresh synthetic data and successful owned-resource teardown.

Backend mypy (three changed source files), web TypeScript and changed Python
Ruff checks passed. The generated OpenAPI/client contains the schedule route.

## Task acceptance reconciliation

| Task | Delivered scope | Required criteria | Named integration / E2E proof | Acceptance gap |
|---|---|---|---|---|
| 030.1 | Schema/repository and draft/active/ended/archived/trash lifecycle | 030.A1, 030.A4 | migrations.py empty/upgrade; lifecycle.py transitions; surveys-module.spec.mjs member journey | A1 includes permanent deletion edge, still pending SURV-090 |
| 030.2 | Revisioned drafts, immutable versions, version binding, isolated duplicate | 030.A2, 030.A3 | lifecycle.py concurrent saves/publications, v1/v2 binding and duplicate SQL checks | Passed in recorded lifecycle runs |
| 030.3 | Transactional manual/scheduled closure and closed restoration | 030.A1, 030.A2, 030.A4 | schedule.py prepare/recover; lifecycle.py cutoff and transition matrix; member UI journey | A1 remains open for permanent deletion |
| 030.T1 | Live migrations, transition/race/version tests, schedule restart test | 030.A1–030.A3 | Named scripts above, actual API/PostgreSQL/worker | Full section-5 edge coverage awaits permanent deletion |
| 030.T2 | Full member lifecycle and public closure UI | 030.A4 | surveys-module.spec.mjs member manages lifecycle and timeout through the real module | Passed; scheduled date field additionally covered |

No permanent deletion implementation or full spike acceptance is inferred from
SQL fixture cleanup. The implementation checkboxes for 030.1/030.3 record the
delivered domain/lifecycle scope; their task acceptance stays open through A1.

## Worker/runner regression after scheduled closure

`./leonaid test-surveys-runner` completed with exit 0 in
`leonaid-surveys-833458328-95758` using the same product source. It passed the
real default/override timeout and stopped/restarted worker checks, all 192
API/PostgreSQL validation cases, validator stop/pause and exact-retry recovery,
and all seven Chromium runner/infrastructure tests (27.5 seconds). The run
verified fresh-context restoration, pending offline edits, hidden-answer cleanup,
strict forged-answer rejection and required matrix completion against real APIs.
Its isolated networks/volumes were removed; no host ports were published.

The source tested by these runs is committed together with this proof update;
only documentation was changed after execution. No public push was performed:
the existing automatic publication rejection still requires explicit approval.
