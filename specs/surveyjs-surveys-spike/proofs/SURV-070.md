# SURV-070 — Aggregate engine and analysis integration

The initial engine increment started at baseline `0ac8da1` on 2026-09-07.
The snapshot increment below starts at `29a33f7`. **070.A1 / 070.A2 and their
integration scenarios are accepted.** The later UI increment below also accepts
070.A3 / 070.S3 and tasks 070.1 / 070.2. Separately authorized raw-response
integration remains open.

## Task ledger

| Task | Delivered building block | Remaining acceptance |
|---|---|---|
| 070.1 | Strict DTOs, immutable PostgreSQL snapshots, authorized filters, worker-delay consistency and real member filter UI | Accepted: A1/A2/A3 and S1/S2/S3 |
| 070.2 | Neutral engine, batch combination, golden snapshot API and chart/table UI | Accepted: A1/A3 and S1/S3 |
| 070.3 | Custom charts and accessible tables delivered | Raw/free-text views and their authorization E2E remain open under A4 |
| 070.T1 | Engine and actual API golden data, aggregate-only/foreign/action/test scope rejection, immutable snapshot and batching/limit checks | Accepted for A1/A2; broader module capabilities remain tracked by SURV-060 |
| 070.T2 | Actual analysis filters, chart/table values, empty states and keyboard tables pass | Raw-route-denial E2E remains open under A4 |

## Aggregate semantics

`aggregateApprovedSurvey` is exported through the neutral package's separate
`analysis` entrypoint. It creates/disposes the same SurveyJS model used by the
runner and uses `profileAnswerError` for partial answer validity. The host must
approve a stored initial-v1 definition before calling it. The function cannot
authorize a user or choose which responses belong in an analysis.

Every selected response increments either relevant or hidden for each question.
Relevant answers are partitioned into valid answered, unanswered and invalid.
Missing ratings/numbers remain missing. Author-defined choices retain scalar
type identity; response-created values never become buckets. Rating buckets
follow the configured scale, including fractional steps. Text/date contents are
never returned. Numeric fields provide sum, mean, minimum and maximum.

Choice percentages use valid answered participants. A participant selecting two
checkbox choices counts once in that denominator, so totals can exceed 100%.
Matrix rows have their own valid answered-cell denominator, missing-cell count
and invalid count. An invalid matrix answer is excluded as a whole; each row is
marked invalid for that response. Hidden matrices do not enter row denominators.

The initial NPS template convention is a 0–10 rating with step 1. Promoters are
9–10, detractors 0–6, and NPS is `100 * (promoters - detractors) / valid answered`.
Other scales receive no NPS metric. Empty means, NPS and percentages are null.
The engine retains counts/sums so future batch combination can recompute metrics
from denominators, rather than incorrectly averaging percentages or NPS values.

The private service exposes `/aggregate` alongside its unchanged `/validate`
operation. `aggregate_batch` approves the definition, rejects unknown answer
fields and limits a single batch to 100 records and a 550,000-byte JSON body.
This is a processing-batch limit, not the final survey response limit. The snapshot increment below supplies multi-batch selection and orchestration. The adapter validates
strict DTOs, finite numeric values, matching question IDs and denominator sums.
Errors expose a generic unavailable outcome and no SurveyJS answer diagnostics.

## Golden and package evidence

`tests/fixtures/surveys/analysis-golden.json` deliberately contains five synthetic
answer states, including invalid legacy values and hidden stale text. Assertions
are hand-calculated independently of the implementation:

- Checkbox counts are 2 and 1 over two valid respondents: 100% and 50%.
- NPS has three valid values (10, 9, 0), one invalid value and one missing value;
  mean is 19/3 and NPS is 100/3.
- Numeric values 10 and 20 give sum 30, mean 15, min 10 and max 20.
- Conditional page/question visibility produces distinct relevant/hidden counts.
- Matrix row denominators are two and one valid cells; missing and invalid
  responses have separate counts.
- Text and date values, hidden stale text and invalid choice strings are absent
  from aggregate output. Empty batches retain author buckets with null metrics.
- Type-sensitive scalar choices and fractional-rating boundaries stay distinct;
  unknown answer keys are rejected.

`./leonaid test-surveys-core` exited **0**: 168 existing SurveyJS/Python
comparisons, 23 Python tests and eight Bun tests with 97 assertions (including
four new aggregate tests). The first new fractional-rating test expected a value
slightly above the configured maximum to count. Correcting the fixture to the
shared validation semantics now explicitly verifies that value is invalid.

Strict TypeScript on the new analysis entrypoint, Mypy on both changed Python
application/adapter files and Ruff on the changed Python files passed.

`./leonaid test-surveys-package` passed as
`surveys-package-833458328-10900`, exit **0**. The external consumer imports
`@leonaid/surveys/analysis` from the installed tarball, checks the NPS denominator
and absence of synthetic private text, and verifies analysis code is absent from
the respondent bundle. Existing browser persistence/restart phases passed in
2.8s and 901ms; isolated resources were removed. Dependency versions and MIT/OFL
notices remain unchanged. Own license remains UNDEFINED/manifest UNLICENSED.
[Packed-consumer inventory and entrypoint proof](assets/SURV-070-package.json).

## Private HTTP engine proof

`/bin/sh tools/surveys/aggregate-engine.sh` passed as
`surveys-engine-833458328-12074`, exit **0**. It bundles the service using the
installed pinned SurveyJS 3.0.3 modules and starts a separate private Docker
network without host ports. The actual Python adapter calls the Bun HTTP service:
golden counts/NPS/matrix/relevance, no raw text, empty results, 100-record batches,
over-count/over-size rejection and unknown-key rejection all pass. Stopping the
actual service produces `survey_analysis_unavailable`; starting it again repeats
the full golden proof successfully. Its container and network were removed.
[Sanitized aggregate result](assets/SURV-070-aggregates.json).

The first full `./leonaid test-surveys-aggregates` attempt,
`leonaid-surveys-833458328-10568`, took 854 seconds in dependency installation.
It was deliberately interrupted while preparing to continue development; logs
subsequently showed installation had completed and service startup was underway.
Exit 130 is not a passed test. Its owned containers, volumes and networks were
independently confirmed absent after cleanup.

The repeated full command then passed as
`leonaid-surveys-833458328-13121`, exit **0**, using the completed images. The
actual API-container adapter passed the golden/limit checks, stopped-engine
failure and restored-engine repetition. PostgreSQL/API foundation and the
existing infrastructure browser journey passed, and all isolated resources were
removed. This proves the private engine in the full stack; it still does not
prove the as-yet-unimplemented analysis UI or snapshot/query authorization.

## Immutable analysis snapshots

Baseline `29a33f7` plus this increment's migration, API/client, repository and
live fixtures. `./leonaid test-surveys-analysis` passed as
`leonaid-surveys-833458328-20045`, exit **0**. This closes **070.A1 / 070.S1**,
**070.A2 / 070.S2**, and the actual-analysis portion of **050.A2 / 050.S2**.
The existing infrastructure browser scenario passed; it is not an analysis UI test. Owned containers, volumes and networks were removed, and no
host ports were published.

The member API provides:

- GET `/api/v1/surveys/{surveyId}/analysis/versions`: published version metadata,
  without response data or an implicit choice of version.
- POST `/api/v1/surveys/{surveyId}/analysis`: a stable operation ID plus a filter
  with a required version ID. Status defaults to partial/completed and test data
  defaults to excluded. Date bounds apply to participation creation, inclusive
  `createdFrom` and exclusive `createdBefore`, normalized to UTC.
- GET `/api/v1/surveys/{surveyId}/analysis/{snapshotId}`: the stored immutable
  result, with current permissions and survey lifecycle checked again.

All routes require `view_aggregates`; selecting or reading test-data snapshots
also requires `design`. Resource scope applies to action-linked surveys as well
as standalone grants. Trash blocks ordinary analysis, while archive permits
authorized reads. Snapshot operation replay rechecks these permissions.

The repository holds the survey lock while capturing and processing its
selection, so response/lifecycle writes cannot change that selection. It records
a server timestamp after acquiring the lock. The SQL selection uses persisted
timeout snapshots and answer-change timestamps to classify overdue rows even if
the worker is stopped. An elapsed survey end also closes open rows for analysis
without waiting for the worker. Overall status counts use the same version,
date and test-data scope; selected questions use the requested statuses.

Migration `0030_survey_analysis` stores the public aggregate payload separately
from frozen raw response data needed for later authorized exports. The aggregate
API queries only the public payload on read. Neither storage projection contains
resume credentials or recipient identities; only the private projection contains
raw answer text and participation IDs. Database constraints bind snapshot,
survey and version identities, and a trigger rejects updates. Survey deletion
cascades to these snapshots. SURV-090 must include this table in retention and
deletion/recovery acceptance.

Selected responses are processed in bounded engine batches; global metrics are
recomputed from combined counts and sums. A request is limited to 5,000 selected
responses and 32 MiB of serialized source answers, checked in SQL before loading
them into the application. These are current spike bounds, not a throughput
guarantee. Large-selection latency and the synchronous survey-lock duration
still need the operational assessment under SURV-090.

### Actual API/PostgreSQL assertions

`tools/surveys/analysis_snapshot_live.py prepare` runs with the real worker
stopped. It creates/publishes surveys through the API, then seeds controlled
golden response/history rows and real principals/sessions in PostgreSQL:

- Two versions with overlapping question IDs remain separate even when the
  survey's current published pointer has moved to version two. Version one
  returns the five golden responses and NPS 100/3; version two returns its one
  response and NPS -100. Completed-only selection returns one response/NPS 100.
- In-progress and test responses are excluded by default. Overall status counts
  are one in progress, four partial and one completed. The overdue row is still
  physically `in_progress` while its effective analysis status is partial.
- The actual settings APIs change the global default to five seconds and the
  survey override to two seconds. Existing one-second and 3,600-second response
  snapshots still determine classification. An unchanged public save on the
  overdue participation leaves its answer-change timestamp untouched and its
  effective status partial. Original settings are restored before worker recovery.
- All golden selection/rating/matrix/text/date/relevance denominators match.
  A seeded unknown last-page value is mapped to a generic unknown-page count,
  never copied into the aggregate payload.
- The inclusive date boundary accepts rows created exactly at the start; the
  exclusive boundary rejects rows exactly at the end. Equivalent `+02:00` input
  is returned as UTC. Future-only selection returns zero with null metrics.
- Missing or foreign version IDs, duplicate or unknown statuses, naive or
  inverted dates and an unauthorized recipient filter are rejected.
- An aggregate-only user can create/read/replay real-data snapshots but cannot
  create or read test snapshots. A design-only user and an unauthenticated caller
  cannot create aggregates. Foreign survey/snapshot identifiers are denied.
- Seeded free text, recipient email/name, credentials and participation IDs are
  absent from every inspected aggregate payload. SQL confirms raw text exists
  only in the private snapshot projection, without recipient identity or tokens.
- Removing an aggregate grant denies old snapshot reads and operation replay.
  An action-linked grant without membership grants no access; adding membership
  permits the read, and removing membership denies it again.
- Exact replay returns the same snapshot; reusing the operation with different
  filters conflicts. A direct SQL snapshot update is rejected. After an actual
  public answer save, the original snapshot remains identical as decoded
  JSON, while a new all-status snapshot reflects the changed answer and NPS -50.
- A 101-response selection crosses engine batch boundaries: 100 detractors and
  one promoter yield NPS -9900/101 and mean 10/101. Averaging batch metrics would
  fail these assertions.
- An actual scheduled end elapses while the worker is stopped. Analysis includes
  the open row as partial; archived snapshot reads still return the original
  result, and trash subsequently denies reads.
- 5,001 selected responses and a separate 1,700-response selection exceeding
  32 MiB both return `limit_exceeded`, with no snapshot or operation result
  written. Reducing the same fixture to an empty selection lets the same
  operation succeed, proving failed requests did not leave a false receipt.

The `recover` phase starts the actual worker and waits until it physically marks
the overdue row partial. A new snapshot's questions, status counts, participation
count and last-page counts exactly match the pre-worker analysis. The original
snapshot is still unchanged after both the answer edit and worker execution.
[Sanitized golden snapshot](assets/SURV-070-snapshot.json).

### Migration and supporting evidence

`./leonaid test-surveys-migrations` passed as
`surveys-migrations-833458328-16175`, exit **0**. Empty and existing-data databases
reach revision 0030, repeating the migration is harmless, 17 database invariants
pass and the 46 prior table fingerprints are preserved:
[empty](assets/SURV-070-migrations-empty.json),
[upgrade](assets/SURV-070-migrations-upgrade.json),
[baseline](assets/SURV-070-migrations-baseline.json).

The initial snapshot run (`…-16288`) passed the original API/worker scenarios and
cleanup. Mypy then identified an overly broad inferred type for the default
status list; an explicitly typed factory corrected it. The expanded run (`…-17916`) also passed. The final run above additionally
distinguishes persisted timeout snapshots from current settings and exercises
an unchanged public save. These runs include the resolved response-filter DTO and all additional boundary,
action-membership, deadline and limit cases. Final Mypy on four application files
and member-app TypeScript passed; generated OpenAPI/client includes all three
routes. Source and test Ruff checks and `git diff --check` passed.

## Remaining acceptance

After the UI increment below, 070.A4, 070.T2 and task 070.3 remain open for
separately authorized individual/free-text routes and their E2E denial journeys. The private raw projection is not itself a delivered
raw-response view or export. Preview/test participation creation remains under
060.4; this increment proves selection isolation using controlled database rows.

## Analysis UI and neutral result components

Baseline `91e9fbe` plus this increment. The first full browser run passed as
`leonaid-surveys-833458328-22924` (two tests, 5.2s). The expanded
`./leonaid test-surveys-analysis` run passed as
`leonaid-surveys-833458328-24499`, exit **0**, two Chromium tests in **10.2s**.
Both include the real snapshot API/PostgreSQL/worker assertions above and
verified isolated teardown without published host ports.

The LeonAid detail page provides **Antworten auswerten** only with
`view_aggregates` on a non-deleted survey. Its version list and submissions use
the generated client. Filters select a published version, partial/completed/
in-progress states and a creation-time range with an explicit displayed time
zone. Only designers see the test-data selector. Applied snapshot metadata stays
visible independently of edits to the next filter request. Rejected permissions
or lifecycle operations clear a previous result; an uncertain response retains
the exact operation ID and body for an explicit retry.

`@leonaid/surveys/analytics` renders `SurveyAnalytics` from the immutable
server result, with host-supplied messages and number locale. It does not fetch
raw answers or import the aggregate engine. Separate scoped CSS supplies choice,
rating and matrix bars, numeric/NPS summaries, per-question denominators and
last-page counts. Status counts describe the same version/date/test scope before
the chosen status filter; selected participation count describes the displayed
question aggregates. Each distribution has an equivalent native details/table
view, keyboard-accessible without a mouse or chart tooltip. Multiple-selection
denominators and the limited meaning of last-page counts are explained.

### Browser assertions

`tests/e2e/surveys-analytics.spec.mjs` runs through the actual member UI with a
synthetic administrator at 1280 × 900 and then 390 × 844. It captures successful
real API responses and compares visible counts, chart labels and every choice/
rating/matrix table cell with that exact snapshot. It additionally checks:

- Default status/test selection and separate pre-filter status counts.
- A changed filter cannot silently relabel the previous immutable result.
- Completed-only version one has one response and NPS 100; version two has one
  response and NPS -100. Versions never merge implicitly.
- A future date selection has zero participants, meaningful missing metrics and
  an explanatory empty state without NaN values.
- Including all statuses yields six responses and the golden NPS -50.
- Keyboard Enter opens the NPS data table, with all values matching the chart.
- The test forwards a successful snapshot creation but aborts its HTTP response.
  Explicit retry sends the identical body and operation ID and receives the
  already committed snapshot ID.
- The mobile matrix/choice layout keeps labels and tables visible without
  horizontal document overflow. Reading the initial snapshot again after these
  subsequent requests returns the original result unchanged.

These assertions prove **070.A3 / 070.S3**. The keyboard-table portion of A4
also passes, but A4 and 070.T2 remain open until the real individually authorized
response/free-text routes and their denial journeys are implemented.

### Packed integration and visual review

`./leonaid test-surveys-package` passed as
`surveys-package-833458328-24580`, exit **0**, with both existing browser phases
(2.9s and 1.0s) and successful isolated cleanup. The independent installed
tarball renders the new analytics component with English host overrides using
React server rendering, verifies NPS and table markup, and rejects private text
in the output. Its respondent bundle excludes both analysis and analytics
modules. This is a packed-component rendering proof, not a separate analytics
browser journey in the demo. [Inventory and entrypoint evidence](assets/SURV-070-analytics-package.json).

No runtime dependency was added for charts: bars use scoped CSS. Existing
SurveyJS MIT/OFL handling remains unchanged; own license is UNDEFINED. The
member TypeScript check and whitespace diff check pass.

The initial desktop/mobile screenshots were inspected. A too-dark background
track used the host's muted **text** token. It has been corrected to the host's
`surface-muted` token. The final `./leonaid test-surveys-analysis` run passed as
`leonaid-surveys-833458328-25376`, exit **0**, two Chromium tests in **9.4s**,
with all API/worker assertions and verified cleanup. The corrected desktop/mobile
bars and tables were visually inspected: zero tracks are visually distinct from
filled answers and numeric labels remain legible.

[Desktop NPS chart and table](assets/SURV-070-analytics-chart.png),
[mobile multiselect chart and table](assets/SURV-070-analytics-mobile-chart.png).
The desktop component capture temporarily makes the sticky host topbar static;
the mobile capture retains it, obscuring the heading at the capture boundary
but not the displayed chart/table values. This is a screenshot limitation, not
a claim of a complete accessibility audit. The real browser keyboard/table and
no-document-overflow assertions are separate from this visual review.
