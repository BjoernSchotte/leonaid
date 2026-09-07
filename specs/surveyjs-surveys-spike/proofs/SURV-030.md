# SURV-030 — Lifecycle and version evidence

Status: **accepted** for SURV-030. The final lifecycle matrix and current-schema
migration acceptance below close 030.A1 and 030.T1. Earlier dated sections retain
the evidence and limitations at their execution time; later sections supersede
their open acceptance status. The complete spike remains in progress.

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
| 030.1 | Schema/repository and draft/active/ended/archived/trash lifecycle | 030.A1, 030.A4 | migrations.py empty/upgrade; lifecycle.py transitions; surveys-module.spec.mjs member journey | Passed: current-schema migration and final lifecycle matrix below, plus SURV-090 erasure evidence |
| 030.2 | Revisioned drafts, immutable versions, version binding, isolated duplicate | 030.A2, 030.A3 | lifecycle.py concurrent saves/publications, v1/v2 binding and duplicate SQL checks | Passed in recorded lifecycle runs |
| 030.3 | Transactional manual/scheduled closure and closed restoration | 030.A1, 030.A2, 030.A4 | schedule.py prepare/recover; lifecycle.py cutoff and transition matrix; member UI journey | Passed: final lifecycle matrix and actual erasure below |
| 030.T1 | Live migrations, transition/race/version tests, schedule restart test | 030.A1–030.A3 | Named scripts above, actual API/PostgreSQL/worker | Passed: final 35-case matrix, unpublished restore/erasure and post-erasure rejection below |
| 030.T2 | Full member lifecycle and public closure UI | 030.A4 | surveys-module.spec.mjs member manages lifecycle and timeout through the real module | Passed; scheduled date field additionally covered |

Permanent deletion acceptance now uses real durable worker erasure below and
SURV-090 evidence, not SQL fixture cleanup. The current-schema migration and
complete lifecycle matrix close A1; the full spike remains open.

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

## Current-schema migration acceptance

The previous harness expected revision `0031_survey_exports`. It now requires
`0034_survey_recovery_identity`, includes the deletion ledger and installation
identity tables, and validates disabled retention defaults and one non-null
installation identity. The underlying production migrations were unchanged.

```sh
rtk proxy sh tools/surveys/migrations.sh "$PWD"
```

Project `surveys-migrations-833458328-15860` completed with exit 0. Empty → head
and populated pre-survey baseline → head both passed, including repeated upgrades.
All 46 legacy table row counts and SHA-256 fingerprints remained identical before
and after migration and the rolled-back constraint tests. Both paths passed 30
PostgreSQL invariant checks. New checks cover retention bounds and accountable
configuration, recovery identity singleton enforcement, content-free deletion
operation digests, blocked writes/recreation after erasure intent, and persistence
of the ledger after the referenced survey is removed. The temporary container,
volume, image and internal network were removed; no host ports were published.

Sanitized reports: [empty at 0034](assets/SURV-030-migration-0034-empty.json) and
[baseline upgrade at 0034](assets/SURV-030-migration-0034-upgrade.json). These add
current-schema evidence without overwriting the earlier migration reports. They
do not simulate pre-existing closed surveys at 0031 for retention backfill, nor
claim checkpoint continuity or recovery across schema downgrades.

## Complete lifecycle acceptance

Production source remains `99b363e`; this increment changes test coverage and
proof records. The final `tools/surveys/lifecycle.py` and harness content were
unchanged during the accepted run.

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" lifecycle
```

Final project `leonaid-surveys-833458328-16460` completed with exit 0. In addition
to the existing response, scheduled closure/restart, version binding, concurrent
publication/save and duplication checks, the live API/PostgreSQL test now covers:

- 25 manual transition pairs: five states times end/archive/unarchive/trash/restore.
- Five publication pairs: draft and active create a new immutable version;
  ended, archived and trash reject with 409, preserving both summary and version count.
- Five permanent-deletion pairs: only trash accepts a durable request; the four
  other states return 409 without a ledger entry or summary change.
- The actual background worker completes published and unpublished erasure.
  A repeated published-erasure request reports completed; all five later manual
  transitions and publication return 404. PostgreSQL confirms the published survey
  and unpublished draft are absent. This is not direct SQL fixture deletion.
- Unpublished trash still restores to draft; published trash restores to ended.
  The existing manual/scheduled cutoff checks reject public reopening and late writes.

The three Chromium tests passed in 4.6 s: real member/public host identity,
member lifecycle and timeout/schedule controls, and the mobile scoped designer.
The subsequent independent PostgreSQL check confirmed lifecycle/restoration,
action association and settings. Existing response/schedule scripts emitted an
httpx per-request-cookie deprecation warning; their assertions and command passed.
Fresh isolated volumes and currently unused explicit subnets were used without
host ports; owned resources were removed and teardown verified.

An earlier run (`leonaid-surveys-833458328-15893`) passed the new permanent-deletion
matrix and three browser tests (4.7 s). Review then identified missing explicit
publication-from-each-state assertions. The final run above includes those five
additional cases; it is the basis for complete transition acceptance.

Sanitized matrix result: [SURV-030-lifecycle-complete.json](assets/SURV-030-lifecycle-complete.json).
The detailed actual storage deletion/crash and deterministic autosave/completion/
export race proofs remain in [SURV-090](SURV-090.md#deterministic-deletion-interleavings).
Current empty/baseline migration evidence is in the preceding section. Ruff for
both modified Python probes, shell syntax and `git diff --check` passed.

Together these directly satisfy 030.A1–030.A4 and 030.T1/T2. This accepts SURV-030;
it does not accept the remaining persona matrix, independent recovery checkpoint
continuity, limits/log handling or overall SURV-100 gates.


## Observed lifecycle lock orders

The older lifecycle test used `asyncio.gather` for competing requests. It checked
legal outcomes but did not prove actual overlap or both close/completion orders.
The new `tools/surveys/lifecycle_concurrency.sh` invokes real HTTP/PostgreSQL
assertions against a fresh owned stack, twice. Before dispatch it locks the
survey row, observes the first request in PostgreSQL's blocking graph, starts
the second and observes both blocked before releasing the barrier. An early
response fails the test instead of silently becoming a sequential fixture.

Both iterations passed all eight ordered cases: save A/B, save B/A, save/publish,
publish/save, publication A/B, publication B/A, end/complete and complete/end.
Competing draft/publication operations return 200 then 409 with exactly the
winner's draft and expected immutable-version count/content. End first rejects
completion and leaves the acknowledged partial response; completion first
retains its completed revision/timestamp when end follows. Late saves cannot
replace the acknowledged answer. Exact retries respect current lifecycle guards
and leave complete survey, draft, version, participation and operation row
contents unchanged. No mocked response or persistence adapter is involved.

Command: `sh tools/surveys/lifecycle_concurrency.sh "$PWD"`. Project
`leonaid-surveys-lifecycle-833458328-6584`, exit **0**, both eight-case iterations
passed. All networks were reserved before startup, no host ports were published,
and a separate inventory verified zero owned containers, volumes and networks.
[Rerunnable case results and tested source hashes](assets/SURV-030-lifecycle-concurrency.json)
record the scope. Ruff formatting/lint and shell syntax pass. The aggregate
manifest now includes this additional integration leaf (38 checks total); the
new complete aggregate has not yet passed.

Two preceding attempts are not acceptance evidence. Project `99679` reached all
ordered outcomes but the newly written test wrongly expected a public completion
retry to succeed after survey end. The existing active-survey guard correctly
returned 409; the assertion now checks that guard and unchanged stored results.
Project `2756` failed Twenty readiness before reaching the corrected assertions.
Both projects were independently verified removed. The final successful run used
only two concurrent owned service stacks.

This accepts **030.T1a / 030.S2**, the controlled-concurrency portion. It does not
automatically close other unchecked companion scenarios, full contract coverage,
the complete CI lane or recovery acceptance.


## PostgreSQL migration readiness correction

The migration harness now checks TCP readiness on `127.0.0.1`, matching the
network path used by the migration client. A separate cold-start experiment with
a delayed init script proved that the temporary initialization server can report
Unix-socket readiness while TCP is still unavailable; the final TCP-ready server
accepted real SQL writes. The fix changes readiness detection only.

`sh tools/surveys/migrations.sh "$PWD"` then passed twice, exit **0** each time:
projects `surveys-migrations-833458328-11520` and
`surveys-migrations-833458328-11965`, approximately 65 and 37 seconds. Both runs
proved empty and existing-data upgrades, repeat migration and 30 PostgreSQL
invariants. Separate inventories confirmed zero owned containers, volumes and
networks after both runs. No host ports were published.

Related annotation corrections pass the actual CI mypy path selection (272
source files); restore-state tests pass all 14 cases. The seven gate-controller
tests and the network-test-double policy tests pass. Formatting-only browser
changes preserve the reviewed network-fault behavior. These targeted results do
not constitute a successful full aggregate or full CI run.
