# SURV-080 — Export implementation evidence

The initial tabular increment started at `8add0a6`; subsequent baselines are below.
**080.1–080.3 and 080.T1–080.T2 are accepted.**
Criteria 080.A1–A6 are proven below. SURV-080 is accepted for the specified spike
scope; the overall plan and SURV-090 deletion work remain incomplete. Earlier sections record the
evidence and limitations of their respective increments.

## Task ledger

| Task | Delivered building block | Remaining acceptance |
|---|---|---|
| 080.1 | CSV, response XLSX and analysis XLSX through real worker/private storage and parsed API/browser downloads | Accepted; see tabular task acceptance below |
| 080.2 | Native workbook charts, server-side vector PDF charts and dedicated Typst report; PDF visual review and browser downloads | Accepted in consolidated render review below |
| 080.3 | Durable jobs, current permission checks, private storage, recovery and protected downloads | Accepted by terminal job-state review below |
| 080.T1 | Artifact parsing, four export pipelines, real recovery and permission/deletion integration | Accepted against A1, A2 and A3 below |
| 080.T2 | Normal, long-label, empty and actual-worker PDF review; all four browser downloads | Accepted in consolidated render review below |

## Rendering contract

`SurveyExportSource` carries the immutable AnalysisSnapshot, a host-supplied
captured document title and optional typed private responses. `SurveyExportArtifact`
returns bytes, filename, MIME type, render version and SHA-256. It does not reuse
invoice-domain documents or perform authorization. The worker loads private
responses only for a permitted raw-export product and freezes its document title
as part of the job input.

`render_tabular` supports responses_csv, responses_xlsx and analysis_xlsx using
Python CSV and the already pinned openpyxl 3.1.5 dependency. It rejects missing,
duplicated or status-inconsistent raw selections. Analysis workbook generation
uses only the aggregate snapshot, even when the caller supplies private rows.

### CSV

UTF-8 with BOM, standard CSV quoting and CRLF records. The rectangular header
contains `record_type`, snapshot/filter/version metadata, participation metadata
and stable question columns. One `metadata` record always precedes the `response`
records, preserving filter context even when no responses match. Consumers must
select `record_type=response` when counting or importing participations; the
metadata record is not a participation. All rows have the same column structure.

Each question has `q:ID` and `q:ID:type`. Types distinguish missing, null, string,
number, boolean, array and object. Structured values use canonical JSON; matrix
row columns supplement the complete matrix value. Missing and null cells are
blank but remain distinguishable by type. Empty strings have type string.
Metadata repeats with response rows so concatenated/filter-selected rows retain
context. CSV prefixes formula-like and apostrophe-leading strings with one
apostrophe. Strip that single prefix when decoding string values; leading
apostrophes are themselves escaped so this is reversible. Whitespace and control
prefixes cannot hide formula operators from the guard.

### XLSX

Response workbooks contain Metadata, Questions and Responses. The question
catalogue preserves typed choice values and authored labels, including matrix
rows. Response columns use the same explicit value types as CSV; XLSX readers
that return blank for an empty string can reconstruct it from the string type.
Large integers and raw floats beyond Excel's 15-digit numeric precision are
stored as exact text with type number. Ordinary numbers remain numeric cells.

Analysis workbooks contain Metadata, Questions, Metrics, Distributions, Matrix
rows, Charts and Last page. Counts, sums, means, NPS, missing/hidden/invalid values
and denominators come from the same stored snapshot. Native horizontal bar charts
reference the distribution table's percentage and label cells. The implementation
follows the upstream [bar-chart API](https://openpyxl.readthedocs.io/en/stable/charts/bar.html);
actual visual rendering remains an explicit acceptance gate.

All string cells are explicitly strings, with a quote-prefix hint where useful;
no user text becomes a formula or hyperlink. Unsupported XML characters and
strings longer than 32,767 characters cause `cell_text_unrepresentable`, without
returning an artifact or silently truncating data. This is an enforced format
limit to surface through the future job error state, not an accepted full export
error/retry workflow. ZIP timestamps and document creation/modification times are
normalized to ensure identical XLSX bytes across retries and writer-clock changes.

## Artifact-level verification

Pinned Python runtime command:

```sh
uv run --frozen --no-sync pytest tests/unit/test_survey_tabular_exports.py -q
```

The 18 tests create actual CSV/XLSX bytes and re-open them with independent CSV
and openpyxl readers. They verify hand-calculated NPS 100/3, numeric mean 15,
multiselect counts 2/1 and percentages 100/50, matrix row denominators, empty
results, metadata, Unicode/newlines, malformed raw selections, typed large
numbers, all formula prefixes, reversible apostrophes and no raw text in reports.
Five chart parts reference the aggregate distribution sheet. The tests explicitly
change the writer clock by a decade and still obtain identical bytes. They do
not claim that native charts were visually rendered.

The initial test found XLSX empty-string ambiguity; explicit type columns fix
that representation loss. A later clock fixture initially patched a module as a
class; correcting that fixture made the intended clock-drift check executable.
Mypy also required an explicit optional-string chart-group type. Final tests,
Mypy, Ruff and whitespace checks pass. No runtime dependency or own-license
selection was introduced; own license remains UNDEFINED.

Revalidated on 2026-09-07 against the five-file working-tree increment on
`8add0a6`, using the pinned container
`ghcr.io/astral-sh/uv:0.11.17-python3.13-trixie-slim@sha256:6181d17d152967488408b4ced7b2930cc91c2b39adb7af6fb339965afce3404e`.
The repository was mounted at `/workspace`, working directory `/workspace`,
with `PYTHONPATH=/workspace/src`. All containers used `--rm`, with no published
ports or application service stack.

| Command inside the pinned container | Observed result |
|---|---|
| `uv run --frozen --no-sync pytest tests/unit/test_survey_tabular_exports.py -q` | Exit 0; 18 passed in 0.43 s |
| `uv run --frozen --no-sync mypy src/leonaid/application/surveys/export_rendering.py src/leonaid/adapters/survey_tabular_exports.py` | Exit 0; two source files passed |
| `uv run --frozen --no-sync ruff check src/leonaid/application/surveys/export_rendering.py src/leonaid/adapters/survey_tabular_exports.py tests/unit/test_survey_tabular_exports.py` | Exit 0; all checks passed |

These commands exercise artifact rendering only, not the required isolated
application integration or browser journeys.

## Next required integration

Add the export UI and explicit failure/recovery scenarios, then execute all four
real worker/storage/browser products. Only those
passing integration, E2E and rendering gates can close the still-open SURV-080
criteria. PDF rendering is now implemented and proven through the worker; the
export UI, complete XLSX visual review and recovery matrix remain open.

## Durable tabular jobs — 2026-09-07

Baseline `08a3a19` plus the export-job working-tree increment. The API creates an
immutable request linked to the existing analysis snapshot and an outbox event
in one transaction. Exact operation replay returns the same job identity;
changed inputs conflict. Job titles are captured at request time. Raw response
projections are loaded only for raw products after `export_raw` authorization;
report products require `export_reports`. Test snapshots additionally require
design permission. Job reads/downloads are scoped to the requesting account.

The worker resolves the requesting account, roles, current action memberships
and survey grants from PostgreSQL. It checks them before rendering and again
before making the artifact available. Downloads check current permission before
and after reading the exact stored object version. They return bytes through the
authenticated API with `no-store`, attachment disposition and `nosniff`; neither
storage locations nor presigned URLs are returned. Stored bytes and hashes are
verified. Worker errors are reduced to a stable content-free code. Revoked queued
requests are cancelled. Object references survive cancellation and survey/snapshot
deletion is blocked until controlled retention removes export jobs and objects.

`tools/surveys/exports_live.py` ran in the actual API/worker/RustFS stack via:

```sh
rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid exports
```

Project `leonaid-surveys-833458328-37646`, exit 0, all owned resources removed.
Seven unused explicit subnets, no published host ports. Observed assertions:

- Three tabular jobs survived the deliberately stopped worker and were processed
  after its restart. CSV rows and workbook metrics matched the frozen snapshot;
  actual workbook chart definitions were present.
- Duplicate operation IDs produced one job; changed products conflicted. Pending
  downloads returned 409. Foreign snapshot requests returned 404 and unauthenticated
  reads returned 401. Stored job inputs rejected SQL mutation.
- A report-only member could queue a report but could not queue raw data. Revoking
  that grant before processing cancelled the job without producing an object.
- Anonymous RustFS object reads were denied. After a survey was trashed through
  the real API, every existing job read and download returned 404. Direct survey
  deletion could not orphan the object references.
- Outbox payloads contained only empty JSON objects; job identities are carried
  by the outbox aggregate. Download bodies contained no synthetic session tokens.
- The existing member/public infrastructure browser test passed (1.7 s). This
  is a host regression check, **not** the still-required export UI journey.

Sanitized result: [tabular API proof](assets/SURV-080-tabular-api.json).

Migration command:

```sh
rtk proxy sh tools/surveys/migrations.sh /Users/bjoern/.codex/worktrees/497a/leonaid
```

Project `surveys-migrations-833458328-37939`, exit 0 and verified resource cleanup.
Both empty and populated databases reached `0031_survey_exports` and repeated
migration safely. Twenty-two actual PostgreSQL invariants passed, including
immutable export input, complete metadata before availability, cross-survey
snapshot rejection and retained object references. All 46 pre-survey table
fingerprints remained unchanged. Evidence: [empty](assets/SURV-080-migrations-empty.json),
[upgrade](assets/SURV-080-migrations-upgrade.json),
[baseline](assets/SURV-080-migrations-baseline.json).

The initial full-stack attempt (`37264`) exposed an import-time evaluation of
`asyncpg.Pool[Any]`; deferred annotations fixed API/worker startup. That attempt
failed and was cleaned up. It is not counted as a successful proof.

Final supporting checks: `pytest tests/unit/test_survey_tabular_exports.py
tests/unit/test_migration_policy.py -q` passed 20 tests in 0.50 s; Mypy passed
the five changed export/API/worker modules; Ruff passed all changed Python
modules and proof scripts. OpenAPI generation succeeded and the generated
`downloadSurveyExport` returns a `Blob`; `bun run typecheck:api-client` exited 0.
The binary OpenAPI description was added after the live run; it changes the
generated contract, not download execution. Proof links and whitespace checks
passed. No complete SURV-080 task or acceptance checkbox has been checked.

## Dedicated Typst reports and all four products — 2026-09-07

Baseline `84f4c85` plus the PDF increment. `TypstSurveyRenderer` and
`survey-analysis-v1.typ` use the existing pinned Typst 0.13.1 binary and pypdf
5.8.0 dependency. No new dependency, external chart service, commercial component
or own-license choice is introduced. The report receives aggregate presentation
data only; even explicitly supplying private response rows leaves its bytes
unchanged. Author strings are JSON data, never evaluated Typst code.

Reports include frozen selection/version/date metadata, scoped status totals,
per-question relevant/answered/unanswered/hidden/invalid counts, sums, means,
extrema, NPS, matrix row completeness, vector horizontal percentage bars with
count/denominator/table alternatives, and last saved page counts. German labels
explain denominators and round displayed metrics to at most two decimal places.
Missing percentages read `Nicht verfügbar`, rather than falsely reporting zero.
Question headings remain with their first count table. Chart tables repeat their
question number and distribution context across pages; ordinary long labels
remain with the corresponding row. The implementation uses the documented
[Typst table cell and repeated-header controls](https://typst.app/docs/reference/model/table/).

`python tools/surveys/pdf_render.py` ran against the pinned Dockerfile.core runtime
with the worktree mounted at `/workspace`, exit 0. Normal (4 pages), long-label
(8 pages) and empty (4 pages) reports have byte-identical repeated rendering.
The script parses actual PDFs, verifies IDs and selected golden metrics (NPS
33.33, mean 15), checks page numbering and absence of active annotations/private
text, proves literal handling of `#panic(...)`/HTML text, and exercises stable
errors for a wrong runtime and missing template. Results and hashes:
[render proof](assets/SURV-080-pdf-render.json).

### Font correctness and visual review

An additional Japanese-title probe revealed that Typst silently emits replacement
boxes without compiler warnings. The final adapter therefore inspects actual PDF
text-showing operators using pypdf and rejects glyph zero in the pinned CFF
Identity-H font profile, including form content streams. Unknown font profiles
also fail verification. A real Typst Japanese-title regression now raises
`typst_font_glyph_missing`; ordinary German/Greek Unicode fixtures pass with
unchanged bytes. This is explicit font coverage, **not universal Unicode font
support**. Adding fonts requires extending and proving the font profile.

All final pages of [normal](assets/SURV-080-pdf-normal.pdf),
[long-label](assets/SURV-080-pdf-long-labels.pdf),
[empty](assets/SURV-080-pdf-empty.pdf) and the
[actual worker report](assets/SURV-080-pdf-worker.pdf) were rendered with Poppler
(`pdftoppm -scale-to 1100 -png`) and visually inspected by the assistant.
No clipping, overlap, replacement glyphs or unreadable labels were observed in
these 20 pages. The initial heading and continuation-context issues were fixed
before this final review. This is a recorded visual check, not a PDF accessibility
certification. [Review record and source hashes](assets/SURV-080-pdf-review.json).

### Actual API/worker/storage proof

The final command was:

```sh
rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid exports
```

Project `leonaid-surveys-833458328-41834`, exit 0, no host ports, owned resources
removed and verified. All four jobs were created while the worker was stopped,
then processed and downloaded through the actual API after worker startup.
CSV/XLSX parsing and the PDF text checks passed; the PDF was stored as an exact
private object version. Existing idempotency, raw-export denial, queued grant
revocation, anonymous storage denial and deleted-survey download checks passed
for this extended product set. A separate queued Japanese-title PDF job failed
without storing an artifact; download returned 409, and the persisted outbox error
was only `survey_export_failed`, with no title or raw diagnostics. The host browser
regression passed (897 ms); it remains distinct from the unimplemented export UI
journeys. [All-products result](assets/SURV-080-all-products-api.json).

An earlier all-products run (`40433`) passed before the glyph guard was added.
Only the final `41834` run supports the glyph-failure claim. During local renderer
development, two fixture assertions were corrected (normal results need not
contain missing percentages; Typst emits empty annotation arrays), and an edit
temporarily misplaced the glyph function inside payload construction. The real
render check caught that error; the final rerun and Mypy passed. Final Ruff,
format checks and Mypy pass; no whole SURV-080 acceptance gate is closed here.
# Export UI increment — empty snapshot and lost acknowledgement

Implementation based on `08d4bfc`; the commit containing this section records
the exact source revision. Own license remains UNDEFINED.

- Added the neutral `@leonaid/surveys/exports` entrypoint and scoped export
  styles. Host adapters supply authorization, credentials, translated messages
  and filenames; the package imports no LeonAid services or UI components.
- Connected all four formats to the displayed immutable analysis snapshot.
  Each product shows queued/running/retrying/available/failed/revoked state.
  A lost creation acknowledgement preserves the operation ID and request;
  status polls stop on errors and can be resumed explicitly. Permission/access
  rejection clears the affected job. Authenticated blob downloads use temporary
  object URLs, with no response blob stored in React state or browser storage.
- The member host supplies separate raw/report permissions. Full permission
  persona coverage and export-only navigation remain open; UI hiding alone is
  not acceptance evidence for authorization.

Verification:

- Pinned Bun container: `bunx --no-install tsc --noEmit -p apps/web/tsconfig.json`
  exited 0. `git diff --check` passed.
- `rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid exports`
  exited 0 in project `leonaid-surveys-833458328-45881`. No published host
  ports; private project networks and volumes were removed and teardown checked.
- Existing real API/outbox/worker/RustFS/Typst proof passed for all four products,
  including snapshot values, cancellation, deletion and private storage checks.
- Chromium: 2 tests passed in 10.3 seconds. The new named test in
  `tests/e2e/surveys-exports.spec.mjs` creates/publishes a synthetic definition,
  requests an empty analysis through the UI, creates/downloads every product,
  checks file signatures and CSV snapshot metadata, and confirms all requests
  use the displayed snapshot. Network fault injection commits the first real
  export request before dropping its response; the UI retries the exact body.
- At 390px viewport width, no horizontal page overflow was observed. The
  rendered export panel was manually inspected: all four labels, statuses and
  download buttons are readable with no clipping or overlap.
- First attempt (`44808`) failed because the test read an analysis snapshot
  fixture instead of a definition (HTTP 422). Corrected to `analysis-golden.json`
  before the successful fresh-stack run. No product behavior was weakened.

Evidence: [browser assertions](assets/SURV-080-browser-empty.json),
[mobile panel](assets/SURV-080-browser-mobile.png).

This is incremental evidence, not acceptance of 080.A4 or SURV-080. Remaining:
populated-snapshot browser value comparisons, report-only/raw-denied and revoked
download journeys, failed/retrying worker and storage recovery UI, independent
packed export consumer, XLSX rendered-chart review, and remaining criteria below.

## Populated browser exports and permission revocation

Accepted **080.A4 / 080.S4** and **080.A6 / 080.S6**. The implementation baseline
is `627e02a`; this section, the tests and fixture/parser changes are committed
together. No other SURV-080 criterion or implementation task is accepted here.

| Task | Required criteria | Evidence and disposition |
|---|---|---|
| 080.T2 | A4, A5, A6 | A4/A6 pass through the named browser journeys and independent file parsing; A5 remains open for rendered XLSX review. |
| 080.1 | A1, A2, A4, A6 | A4/A6 accepted; full task remains open pending remaining integration gates. |
| 080.2 | A1, A4, A5 | A4 accepted; full task remains open. |
| 080.3 | A3, A4, A6 | A4/A6 accepted; full task remains open pending complete worker/storage recovery and permission-race gates. |

`tests/e2e/surveys-export-values.spec.mjs` contains two real Chromium journeys:

1. **populated snapshot exports match visible metrics and report-only access denies raw jobs**
   starts with five synthetic responses (four completed, one partial), creates
   analysis through the member UI and compares visible per-question counts,
   means and NPS with its immutable snapshot. It edits an unapplied status
   filter and then requests all four products through the UI: all jobs still
   reference the displayed snapshot, not the unapplied filter. It observes
   completion and saves the authenticated browser downloads for independent
   parsing. A second member has only `view_aggregates` and `export_reports`:
   report actions and a real report download work, both raw actions are absent,
   and direct raw job creation/download requests return 404 without attachments.
2. **revoked report access blocks existing downloads and trash clears a stale download action**
   runs after the fixture removes only the report grant in PostgreSQL. The same
   member can still create/view aggregate analysis, but cannot create reports
   or fetch/download its previously available report. Then an administrator
   creates a PDF, the real lifecycle API trashes the survey while the export
   panel remains open, and the stale download action receives 404. The UI shows
   the access rejection, removes the download button and emits no download.

`tools/surveys/export_browser_live.py verify-revoke` parses the **actual browser
downloads**, not fresh files downloaded by a different client:

- CSV/XLSX contain the same five participation IDs and matching raw text,
  multiselect, matrix, type and status values, including the partial response.
- XLSX snapshot metadata and every question's counts, mean, bounds and NPS
  match the snapshot asserted in the browser.
- PDF contains that snapshot ID, each question's exact count table, NPS 33.33,
  numeric sum 30/mean 15/minimum 10/maximum 20, multiselect 100/50 percentages,
  and matrix 50/50 and 0/100 percentages. Aggregate PDF/XLSX contain no seeded
  private text markers. XLSX includes charts; their visual rendering remains a
  separate, still-open gate.

Execution: `rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid exports`
exited 0 in project `leonaid-surveys-833458328-48277`. Four browser tests passed:
two foundation/empty-export cases in 9.8s, populated export in 12.7s, revocation
in 4.5s. The existing four-product API/worker/private-storage proof also passed.
The preceding run `47430` passed; `48277` repeated the full sequence after adding
the stronger PDF count/metric/distribution assertions. Both used isolated
networks without host ports and completed verified teardown. Python syntax,
shell syntax and `git diff --check` passed; Python/JS files were formatted.

Temporary persona credentials, detailed snapshots and raw downloads stay in
the disposable proof directory and are deleted on teardown. Only sanitized
summaries are retained: [values](assets/SURV-080-browser-values.json),
[permissions](assets/SURV-080-browser-permissions.json).

Remaining work includes renderer/storage retry and crash recovery, complete
job-time revocation/deletion races, rendered XLSX inspection, packed independent
export consumer, export-only navigation, and the other open plan work packages.

## Worker recovery and tabular task acceptance

**080.A1 / 080.S1 and 080.A2 / 080.S2 are accepted.** Together with the existing
080.A4 / 080.S4 and 080.A6 / 080.S6 evidence above, this accepts **080.1**.
Runtime baseline `5f8eab4` is unchanged in this increment; the new integration
probe and harness mode are recorded in the commit containing this section.

| Task | Required criteria | Tests and result |
|---|---|---|
| 080.1 | A1, A2, A4, A6 | Accepted: `exports_live.py`, `export_browser_live.py`, `surveys-exports.spec.mjs`, both `surveys-export-values.spec.mjs` journeys, and `export_recovery_live.py` below. |
| 080.T1 | A1, A2, A3 | A1/A2 accepted; A3 remains open for the full revocation/deletion race matrix. |
| 080.T2 | A4, A5, A6 | A4/A6 accepted; A5 remains open for actual workbook render review. |

The already successful `exports` mode (project `48277`, documented above)
generated all four products with the real worker and private versioned RustFS,
parsed their golden counts/metrics and snapshot/filter metadata, and checked
absence of the synthetic access credentials. Actual browser downloads were
also independently parsed. The new `export-recovery` mode closes the remaining
renderer retry and adversarial tabular integration requirements:

1. **Process exit after upload:** a test-only subclass delegates to the actual
   S3 `put_immutable` method, which uploads and HEAD-verifies a version, then
   calls `os._exit(73)`. This runs inside the production `OutboxWorker`, queue
   and `AsyncpgSurveyExports` handler. The shell requires exactly exit 73.
   PostgreSQL shows the export transaction rolled back (queued job, no stored
   reference) and an unfinished first outbox claim; the real object is readable
   privately but the download API returns 409. Only the fixture claim timestamp
   is advanced to exercise the existing stale-lease recovery code. The regular
   worker reclaims the same event/job and reuses the exact original object
   version and hash; no second object version or job is created.
2. **Unavailable renderer:** a separate test worker process runs with a PATH
   that cannot resolve Typst. The actual subprocess invocation fails through
   the production handler/outbox path. No file becomes available, downloads
   return 409, and persisted error code/detail are both `survey_export_failed`.
   Starting the regular worker recovers the same job; the resulting PDF is
   parsed successfully and contains no raw formula-text answer.
3. **Unavailable storage:** RustFS is actually stopped while the regular worker
   attempts a CSV export. Failure/retry state and download denial are observed.
   Restarting RustFS allows the same job to succeed with a single object version
   and verified download hash.

The recovered XLSX/CSV contain two synthetic responses, including a formula-like
HYPERLINK string with Unicode, an empty string and a fully missing response.
Independent openpyxl/CSV parsing verifies that XLSX cells have neither formula
types nor hyperlinks, CSV applies the documented leading-apostrophe escaping,
Unicode text and multiselect/matrix values survive, and empty strings remain
distinguishable from missing values through their type columns. Both products
are obtained through actual authenticated API downloads after real worker jobs.

Command: `rtk proxy sh tools/surveys/infrastructure.sh /Users/bjoern/.codex/worktrees/497a/leonaid export-recovery`.
Final project `leonaid-surveys-833458328-51058` exited 0: crash and renderer jobs
completed on attempt 2, storage on attempt 3; each has exactly one object version.
Foundation browser regression passed in 1.9s. All owned containers, networks and
volumes were removed and teardown verified; no host ports were published.
The preceding `50025` run passed the three recovery cases before adding the
adversarial XLSX/CSV file assertions. Shell syntax and formatting checks passed.

Sanitized evidence: [recovery results](assets/SURV-080-recovery.json). Credentials
and object locations exist only in the temporary fixture directory and are
removed by teardown. No production fault-injection switches were added.

Remaining: full job-time permission/deletion races, especially cancellation
after an uploaded-but-uncommitted object; retention must account for such
objects even if no committed job reference exists. Also still open: XLSX visual
review, independent packed export consumer, broader export navigation, terminal
failure/retry browser states, and the rest of the overall plan. This acceptance
does not imply SURV-080 or the complete spike is finished.

## Fix: retain uploaded objects when cancelling after a process crash

Baseline `1c468e7` had a reproduced cleanup defect. In isolated project `69731`,
the test process uploaded an immutable XLSX object and exited 73 before the job
transaction committed. The real lifecycle API then trashed the survey. On
reclaim, the worker cancelled the job with a null bucket/reference, leaving the
already uploaded private object untracked. Downloads were correctly denied;
the failing assertion was specifically `Cancelled export lost its uploaded
object reference`. This is distinct from claiming that data was downloadable.

`AsyncpgSurveyExports._cancel` now HEADs the deterministic job object location
before completing cancellation. If an object exists, its bucket/key/version,
hash, size and rendering metadata are retained on the cancelled job for later
deletion. It loads no revoked answers and generates no new file. If no object
exists, cancellation leaves no fabricated reference. Storage errors keep the
operation retryable instead of completing with an untracked object. A shared
`export_filename` function keeps both renderers and the recovery lookup aligned
while preserving the existing names and object keys.

The test reproduces the same failure sequence after the fix and checks the
original object version/hash on the cancelled row plus continued HTTP 404 for
downloads. Evidence: [cancel-after-crash and recovery](assets/SURV-080-cancel-after-crash.json).

Verification on the source in this commit:

- `export-recovery` mode, project `leonaid-surveys-833458328-70559`, exited 0.
  The formerly failing cancel-after-upload-crash sequence passed, together with
  normal crash recovery, actual missing-Typst recovery, actual RustFS outage,
  adversarial tabular parsing and one browser foundation regression (1.0s).
- `exports` mode, project `leonaid-surveys-833458328-71437`, exited 0. All four
  actual worker products passed golden-data parsing; cancellation before any
  upload still has no object reference. Four browser cases passed (9.7s for
  the two foundation/empty cases, 11.5s populated exports, 3.2s revocation).
- Both commands used `rtk proxy sh tools/surveys/infrastructure.sh
  /Users/bjoern/.codex/worktrees/497a/leonaid <mode>` with isolated resources,
  no host ports, and successful verified teardown. The failed pre-fix run also
  terminated and its cleanup completed before source changes or reruns.
- Pinned UV container: `uv run --frozen --no-sync pytest -q
  tests/unit/test_survey_tabular_exports.py`: 18 passed in 0.54s.
- Mypy passed for the four changed application/adapter files. Formatting and
  `git diff --check` passed. No database migration or dependency change.

This closes the reproduced missing-reference defect, not the overall deletion
feature: SURV-090 must still remove retained objects and database records,
including retry/backup recovery. Full SURV-080 acceptance also remains open for
the remaining permission/race and workbook-render gates.

## Independent packed export consumer

The increment based on `8dc42ad` adds a separate export page to the independent
consumer. It installs the packed package in a fresh consumer directory, without
workspace resolution or LeonAid application imports. Its own SQLite backend
implements the export adapter and persists both the job and immutable CSV bytes.
The host supplies its own messages, styling and supported product list.

Verification: `rtk proxy sh tools/surveys/package.sh
/Users/bjoern/.codex/worktrees/497a/leonaid` exited 0 in isolated Docker project
`surveys-package-833458328-74032`. The first Chromium journey passed in 3.8s;
the restart journey passed in 1.6s. No host ports were published, and teardown
was verified. The test commits a real request before dropping its acknowledgement,
then retries the identical operation through the UI. The downloaded CSV contains
the saved answers and selected snapshot identity, with the expected filename.
After backend restart, the same job and exact file contents remain available;
an anonymous context receives HTTP 404 and downloads use no-store.

The packed bundle inspection verifies that exports are absent from the respondent
bundle and that the independent export bundle excludes the SurveyJS renderer,
runner, editor and analytics. Exact dependency inventory and measured unminified
bundle sizes are in [package evidence](assets/SURV-080-independent-package.json).
No commercial component was introduced; own license remains UNDEFINED.

The UI has [desktop evidence](assets/SURV-080-independent-exports.png) and
[390px mobile evidence](assets/SURV-080-independent-exports-mobile.png).
The browser asserts a visible download control and no horizontal overflow.
Manual review of the mobile image confirms readable labels and no clipping.

Scope: this minimal independent host intentionally implements synchronous CSV
export only. It proves package integration, persistence, retry identity and
bundle separation; it does not stand in for LeonAid worker, permission or
four-format acceptance. Those have separate evidence above. The component keeps
its displayed job in memory; host-driven restoration of job lists is not claimed.
Remaining SURV-080 permission/race and workbook-render gates stay open.

## Export-only member navigation and frozen selection

Baseline `87d7d51` required `view_aggregates` to reach the export UI, despite
`export_raw` and `export_reports` being independent capabilities. The member UI
now offers **Antworten exportieren** when an exporter lacks aggregate access.
Members with aggregate access retain the existing displayed-snapshot workflow.

The new `listSurveyExportVersions` and `createSurveyExportSelection` operations
require either export capability. Selection creation uses the existing locked,
immutable snapshot transaction and actor-scoped idempotency. Its response is a
strict metadata projection: ID, survey ID, version, resolved filters and timestamp.
It exposes neither aggregate values nor individual answers. Existing analysis
and response-reading endpoints retain their separate checks; test selections
still require design permission. Job creation and downloads retain their existing
product-specific and current-permission checks. OpenAPI and the client were
regenerated from the actual transport contracts.

Verification on this increment:

- `rtk proxy sh tools/surveys/infrastructure.sh
  /Users/bjoern/.codex/worktrees/497a/leonaid exports`: exit 0, isolated project
  `leonaid-surveys-833458328-76423`, no host ports, verified teardown.
- Real worker/storage regression: all four export files parsed against frozen
  input, with existing cancellation, idempotency and denial checks passing.
- Five Chromium cases passed: foundation/empty exports (two cases, 7.9s),
  populated exports and the new export-only journey (two cases, 20.4s),
  then existing permission-revocation/trash coverage (one case, 3.3s).
- New browser case in `tests/e2e/surveys-export-values.spec.mjs` uses distinct
  members granted only `export_raw` or only `export_reports`. Each creates its
  selection through the UI and downloads its two products from the real worker.
  It checks metadata-only/no-store responses, identical replay, conflicting
  replay rejection, denied test selections, forbidden aggregate/raw-reading
  routes and rejection of the other product permission. Both run at 390px.
- Pinned UV container: Mypy passed for the three changed backend source files.
  Pinned Bun container: `bun run --cwd apps/web typecheck` exited 0.
  Formatting and `git diff --check` passed.

Sanitized [assertion summary](assets/SURV-080-export-only.json) and
[mobile report-export view](assets/SURV-080-export-only-mobile.png) are retained.
The browser asserts no horizontal overflow. Manual full-page inspection confirms
readable export controls; the fixed host navigation appears at the captured
scroll position, so the image is not a separate proof of all sticky-layout states.
Session credentials and downloaded raw files remain temporary test artifacts.

This resolves the export-only navigation gap. It does not close the overall
SURV-080 permission/race gate or the workbook-render review. In particular,
selection-time grant revocation races still need dedicated coverage, alongside
the remaining job and deletion scenarios.

## Permission boundary acceptance

The test increment based on `8e5a977` exercises the production outbox and S3
adapters with a member whose only permission is `export_raw`. A test-only storage
subclass commits grant deletion on a separate database connection after an actual
upload or read. It does not replace file IO, authorization, rendering or queue
processing and adds no production fault-injection option.

`rtk proxy sh tools/surveys/infrastructure.sh
/Users/bjoern/.codex/worktrees/497a/leonaid export-permissions` ran in project
`leonaid-surveys-833458328-77821`. All integration assertions passed, as did the
real member/public browser foundation case (902ms). The run exited 0, with no
published host ports and verified resource cleanup.

The executable `tools/surveys/export_permissions_live.py` proves:

- Revocation before processing cancels the real queued job without an object.
- Revocation after actual PUT cancels the job and retains the versioned object
  reference for retention; it never becomes an authorized download.
- Revocation after actual GET but before return rejects delivery with
  ResourceNotFound. A successful authenticated HTTP download before revocation
  establishes that the file existed and was readable; later HTTP requests deny it.
- In every revoked state, selection replay, version listing, job replay, job
  status and download return HTTP 404. Error responses contain no attachment header.

Evidence: [sanitized boundary assertions](assets/SURV-080-permission-boundaries.json).
No session tokens, object paths or file contents are in that artifact.

Acceptance 080.A3 / scenario 080.S3 now combines this evidence with the previous
`76423` exports run (deleted-survey downloads and anonymous object access),
`70559` recovery run (survey trashed after upload/crash, then reclaimed and
cancelled with original reference), and the populated browser revocation checks.
Together they prove queued and existing artifacts are inaccessible after grant
revocation or survey deletion. 080.T1 is accepted because its A1/A2 golden-data,
formula-safety and real failure/recovery evidence was already accepted above.

This does not claim permanent deletion of objects: that is SURV-090. Selection
revocation during an in-flight aggregation, broader role changes and terminal
failure browser states remain further hardening/acceptance work. The scope of
A3 is the specified queue/download revocation gate, not all possible concurrency
interleavings across the entire module. SURV-080 remains incomplete until its
remaining tasks and workbook-render gate pass.

## XLSX consumer render review: reproduced failure

On source baseline `601520d`, `tools/surveys/xlsx_render.py` creates normal and
long-label workbooks through the production `render_tabular` implementation and
the existing frozen synthetic snapshot. It does not author a substitute workbook.
Pinned UV execution exited 0; the generated file hashes and sizes are recorded in
[baseline workbook evidence](assets/SURV-080-xlsx-before.json).

LibreOffice 7.1.1.2 (build fe0b08f4af1bacafe4c7ecc87ce55bb426164676) converted
both actual XLSX files to PDF using calc_pdf_Export. Conversion used a separate
UserInstallation under `/private/tmp/leonaid-surveys-xlsx-render-497a`, leaving
normal application profiles untouched. The sandboxed attempt terminated with
signal 6; the authorized native invocation exited 0. This is one concrete consumer
render, not a claim of compatibility with every Excel/LibreOffice release.

Both tiny fixtures produced 24 pages. Text extraction shows the metrics table
split into five horizontal slices and distributions into four. Manual inspection
of page 17 confirms the chart is cut off horizontally: the 0–100 percent axis
ends visibly around 60 and bars continue beyond the page. Long titles and labels
are also clipped. Evidence: [normal chart failure](assets/SURV-080-xlsx-before-normal.png)
and [long-label failure](assets/SURV-080-xlsx-before-long.png).

Reproduction after fixture generation:

```sh
rtk proxy /Applications/LibreOffice.app/Contents/MacOS/soffice \
  -env:UserInstallation=file:///private/tmp/leonaid-surveys-xlsx-render-497a \
  --headless --convert-to pdf --outdir .artifacts/surveys-xlsx \
  .artifacts/surveys-xlsx/normal.xlsx .artifacts/surveys-xlsx/long-labels.xlsx
```

080.A5 remains failed/open. Required corrections include explicit usable page
layout and print areas, chart placement that does not split a chart across pages,
and readable handling of long titles/labels while retaining full source labels
in the workbook. Re-render and inspect corrected consumer output before accepting
080.2 or the overall export-render gate. No renderer fix is claimed in this increment.

## XLSX layout correction and consumer regression

The increment after `fa18089` corrects the reproduced chart/page split in the
production tabular renderer. Renderer metadata advances to `survey-tabular-v2`.
Tables have explicit print areas, fit one page wide on A3 landscape, repeat their
headers, and use wrapped cells with calculated row heights. Metadata values have
a wider column. Numeric metrics retain their full stored precision with a
readable two-decimal display format.

Charts use A4 portrait, explicit print bounds and a manual page break between
charts. Each chart includes its question/row identity. Long titles and category
labels use explicit ellipses; the full source text remains in Questions and
Distributions. Numbered `chart_label` values in Distributions map the displayed
labels back to the full choices without changing counts, denominators or values.
There is no legend because each chart contains a single percentage series.

LibreOffice 7.1.1.2 rendered the two production XLSX fixtures again. The normal
fixture now has 12 pages and the long-label fixture 16, compared with 24 each
before correction. Extracted text places five charts on five separate pages in
each file; every chart page contains its complete 100-percent scale and axis
caption. [Workbook hashes](assets/SURV-080-xlsx-layout-workbooks.json) and
[consumer page assertions](assets/SURV-080-xlsx-layout-consumer.json) identify
this revision. Manual inspection covered the normal chart, the long-label NPS
chart and a long-label distribution table. The full scale, question reference,
numbered choices and wrapped source text are visible in the inspected views:
[normal chart](assets/SURV-080-xlsx-layout-normal.png),
[long NPS chart](assets/SURV-080-xlsx-layout-long.png),
[full-label table](assets/SURV-080-xlsx-layout-table.png).

Validation:

- Pinned UV container: `pytest -q tests/unit/test_survey_tabular_exports.py`:
  18 passed in 0.47s, including unchanged values, safe text and deterministic output.
- `infrastructure.sh <worktree> exports`: exit 0, project
  `leonaid-surveys-833458328-80100`, no published ports and verified cleanup.
  All four worker files passed parsing; five Chromium cases passed (foundation
  and empty exports 9.6s, populated and export-only cases 21.1s, revocation 3.7s).
- Mypy found a reused string/integer loop variable. After the test process fully
  terminated, renaming that variable passed Mypy. Re-generating both workbooks
  produced the exact same hashes as before the rename, so rendered evidence
  still matches the final source. `git diff --check` passed.

This is a proven correction of the observed split-chart defect, not completion
of 080.A5: full page-by-page review, empty analysis and response-workbook visual
coverage remain open. Very long cells are still bounded by Excel row-height
limits; no claim of unlimited text fitting on printed pages is made. The initial
A3 table/A4 chart paper choices should be evaluated in that remaining review.

## Empty analysis and raw-response workbook review

The increment based on `b1d648f` extends the production-renderer fixture command
with an empty analysis and five synthetic raw responses from the golden fixture.
Normal and long-label analysis file hashes remain unchanged. The raw workbook
initially fit all answer/type columns onto one A3 page, producing unreadably small
print. Its Responses sheet now prints at 100 percent with the participation-ID
column repeated on every horizontal continuation; the workbook remains a normal
wide, filterable table. The fixture prints on three readable continuation pages,
plus its metadata and question catalogue. Manual inspection covered all three
response pages, including matrix JSON, free text, missing values and repeated IDs.

Empty charts now explicitly say `No valid answers` when their denominator is
zero. They keep the question/row identity and do not draw invented percentage
bars. This distinguishes absent observations from an observed zero-percent
category. The empty chart view was manually inspected after the change.

Validation: `tools/surveys/xlsx_render.py` ran through the pinned UV environment;
LibreOffice 7.1.1.2 converted the actual files using the existing isolated profile.
Both commands exited 0. PDF extraction verifies that all five participation IDs
are present on each of the three raw continuation pages, and all five empty
chart pages explicitly state no valid answers. The existing 18 tabular tests
passed in 0.54s after the final changes. `git diff --check` passed. This change
only affects print settings and empty-chart captions; the prior full worker/UI
regression remains the integration baseline, without claiming a rerun here.

Evidence: [four workbook hashes](assets/SURV-080-xlsx-expanded-workbooks.json),
[consumer assertions](assets/SURV-080-xlsx-empty-responses.json),
[empty chart](assets/SURV-080-xlsx-empty.png), and
[raw continuation](assets/SURV-080-xlsx-response-continuation.png).
The literal SENSITIVE markers in the raw image are synthetic fixture strings,
not participant data.

080.A5 remains open pending the consolidated page-by-page review of all report
sheets; these targeted views do not substitute for that remaining acceptance.

## Consolidated render acceptance

On `f502581`, the assistant inspected every page in the four XLSX consumer
outputs: normal analysis (12 pages), long-label analysis (16), empty analysis
(12), and raw responses (6), totaling 46 pages. Contact views covered every page;
detailed views in the preceding increments covered charts, long text and all raw
continuations. The original workbook hashes were rechecked against the recorded
production outputs before retaining the final consumer PDFs.

[Page ledger and exact hashes](assets/SURV-080-xlsx-final-review.json) distinguish
manual review from automated extraction assertions. The complete reviewed output
is retained for [normal](assets/SURV-080-reviewed-xlsx-normal.pdf),
[long labels](assets/SURV-080-reviewed-xlsx-long-labels.pdf),
[empty analysis](assets/SURV-080-reviewed-xlsx-empty.pdf), and
[raw responses](assets/SURV-080-reviewed-xlsx-responses.pdf).

Observed results:

- All five charts in each analysis file occupy complete separate pages with
  visible axes, labels and boundaries. Single-series legends are intentionally
  absent; the percentage caption identifies the series.
- Metadata, question catalogue, metrics, distributions, matrix rows and last-page
  tables stay within their print areas. Table continuations repeat their headers.
  Long source labels wrap in their cells and are preserved; chart abbreviations
  are explicit and mapped through question/row IDs and numbered chart labels.
- Empty results keep question context and explicitly label absent valid answers.
  There are no invented bars or misleading zero-valued means/NPS.
- Raw continuation pages retain all five participation IDs and their respective
  answer/type columns. These three response pages were also inspected separately
  at the larger render size in the preceding increment.
- No cut-off chart boundaries, missing source columns or replacement glyphs were
  observed in the inspected corpus. The known A3 data-table/A4 chart layout,
  consumer version and Excel row-height/font limitations remain documented.

080.A5 and 080.S5 are accepted by this XLSX review together with the existing
20-page Typst normal/long/empty/worker review and glyph rejection proof above.
080.2 is accepted against A1/A4/A5: the existing real worker/browser checks prove
values and delivery; the dedicated template and native workbook charts now have
recorded consumer-render evidence. 080.T2 is accepted against A4/A5/A6, including
the previously proven four downloads and denied raw-export journey.

This is a bounded spike acceptance for the synthetic corpus and named consumer,
not universal font support, PDF accessibility certification or a promise that
arbitrary text fits on a printed page. The final review required no further
source edits or rerun of unchanged integration code. 080.3 still needs its final
job-state/UI review; SURV-090 and the remaining overall plan are not completed.

## Terminal job-state acceptance

The increment based on `fbb141f` adds `export-states` mode to the isolated live
harness. `tests/e2e/surveys-export-states.spec.mjs` creates a real PDF export in
the member UI. `tools/surveys/export_states_live.py` processes that exact event
using the production outbox, handler and S3 adapter. The test process temporarily
uses a PATH without Typst, so all five attempts execute a real failing renderer
lookup. The retry policy retains five attempts but uses zero delay for this
bounded test. Atomic fixture-file signals stop processing until the browser has
observed the retry state; no job-status API response is mocked.

The browser proves queued status, a failed status-network request and recovery
through the status-check button, visible automatic retry, and terminal failure
without a download button. It then requests a fresh job through the same UI.
The restored real Typst renderer generates the PDF, the worker stores it, and the
browser downloads the actual file. The replacement has a new operation and job
ID but the same immutable snapshot. The failed job remains a dead-letter record
with no object; its persisted error code/detail contain only the generic failure.

Command: `rtk proxy sh tools/surveys/infrastructure.sh
/Users/bjoern/.codex/worktrees/497a/leonaid export-states` exited 0 in project
`leonaid-surveys-833458328-82845`. The export journey and member/public foundation
case passed (two Chromium cases, 8.0s). The worker probe passed and was joined
before teardown. No host ports were published; cleanup was verified.

Evidence: [worker assertions](assets/SURV-080-state-worker.json),
[browser assertions](assets/SURV-080-state-browser.json), and
[captured failure state](assets/SURV-080-state-failed.png). Session credentials,
job handshakes and temporary downloads were not copied into published proof files.
Formatting and `git diff --check` passed. No production source change was needed
for these states: this increment proves the previously implemented behavior.

080.3 is now accepted against A3/A4/A6 plus the requested retry/error-state
behavior. The earlier proofs cover atomic creation, restart/crash and real storage
outage recovery, current permissions, deletion invalidation, private downloads,
all four products and independent package integration. All tasks and acceptance
criteria in SURV-080 are accepted within the documented spike boundaries.
This does not complete the larger plan: permanent deletion/retention/backup
recovery, remaining module/package work and final combined journeys remain open.
