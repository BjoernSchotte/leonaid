# SURV-010 — Response persistence evidence

Date: 2026-09-06. Status: partial; full validation parity remains open. This is not a completed survey module.

## Checked items: 010.1, 010.4, 010.T2, 010.A2–A5

The implementation provides typed FastAPI endpoints and a PostgreSQL transaction
adapter for draft creation/loading/saving, immutable publication, public
version loading, participation start, response save/restoration and completion.
The canonical OpenAPI and generated TypeScript client were regenerated.

`./leonaid test-surveys-responses` passed from a new isolated Compose project
with explicit non-overlapping Docker subnets and no host port publication.
It ran migration, authenticated API/database foundation, response contract and
existing member/public browser smoke, then removed its own containers/volumes.
Subsequent source fixes and typed response models were rebuilt into the dedicated
survey worktree API and verified again with the expanded `tools/surveys/responses.py`
contract through `docker compose run --no-deps ... api` (exit 0).

The expanded live contract proves both Krapfentaxi and Golf examples:

- Anonymous callers cannot create authoring drafts; a real synthetic member can.
- Published JSON comes from the server; participation binds its version.
- Incomplete required answers and partial fixed matrices can be saved.
- Forged boolean/numeric/choice/unknown answers are rejected without advancing
  the accepted response revision. Incomplete final submission is rejected.
- Acknowledged answers and current page restore from PostgreSQL.
- Duplicate operations return the original result; changed payloads and stale
  revisions conflict. Repeating completion does not create another response.
- With a one-second configured inactivity timeout, an actual 1.2-second wait
  produces partial status; a changed answer resumes the same participation.
- Changing a prior answer removes the now-hidden follow-up from stored answers.
- Complete submissions become terminal. Incorrect respondent credentials cannot
  access a known participation. SQL assertions verify final data and cardinality.

The final contract cleans up its synthetic surveys. Session secrets remain in
ignored local artifacts, not in proof documents or source control. Respondent
access uses per-participation HttpOnly/Secure cookies; the transport's start
secret is not stored in cleartext in operation records or returned in JSON.

## Supporting checks and remaining boundaries

- 21 focused unit/regression tests passed for survey validation/lifecycle,
  malformed definitions and existing OpenAPI/architecture policy.
- Strict mypy passed for the four new service/adapter/transport/validation sources.
- The regenerated API client passed TypeScript checking.
- Seven shared fixture cases ran against actual SurveyJS 3.0.3 in pinned Node
  and the Python validator: final validity and visibility matched. The comparison
  caught and corrected an erroneous shared namespace for page/question names.

Reproduce the current comparison with `./leonaid test-surveys-core`. It runs
the actual runner model factory in the pinned Bun container, then the Python
comparison and regression tests in the pinned Python container. Inputs are
committed in `tests/fixtures/surveys/validation-cases.json`; outputs stay local.

These seven cases do not establish parity for every initial capability, every
condition or every malformed input. The Python validator is still a candidate;
010.2, 010.3 and 010.A1 remain open pending the full comparison and selection.
Restart/chaos proof, invitations and the full lifecycle UI remain open.


## Browser autosave and recovery proof

`./leonaid test-surveys-runner` rebuilt the current source in the isolated
`leonaid-surveys-833458328-14466` project, with empty volumes, explicit unused
subnets and no published host ports. The real migration, API/PostgreSQL
foundation and response contract passed. Playwright Chromium then passed all
three tests in 11.7 seconds: identity/public infrastructure plus two runner
scenarios in `tests/e2e/surveys-runner.spec.mjs`.

The desktop journey (1280×960) proves 010.A3, 010.A4 and 050.A5:

- Type text, wait for acknowledgement while the field still has focus, close the
  entire context and restore in a fresh context with the same protected cookies.
- After a real 2.2-second wait against the configured two-second timeout, the
  same participation is partial and retains exact text. Restoration emits zero
  save requests, including after the debounce interval.
- Change the earlier rating: the now-hidden answer disappears from the server
  snapshot, stays absent after back/forward navigation, and saved page-two text
  and page position survive reload.
- Complete the questionnaire and verify completed server state and the thank-you
  page after reload, using the same participation ID.

The mobile journey (390×844) disconnects the actual browser network while typing.
The runner displays an error and retains edits in memory; reconnecting saves the
pending text and a reload restores it. This does not prove unsent edits survive
closing the browser; no persistent client answer cache is implemented. The broader
050.A3 criterion remains open until that negative closure case is tested.

010.4 is implemented through SurveyJS onTyping events, a 400ms debounce and
immediate page-change flushing, together with the proven backend timeout.
The runner is a separate package entrypoint. LeonAid supplies its generated API
client through the host adapter and uses HttpOnly resume cookies.

Supporting checks: three save-coordinator tests passed (17 assertions), covering
late acknowledgement/new edits, exact retry after an uncertain write, and a
corrected snapshot following explicit rejection. Package TypeScript and public
Astro checks passed (22 files, zero errors/warnings); Prettier and the dependency
allowlist/negative fixtures passed. Own license remains UNDEFINED.

The retained local screenshot `.artifacts/surveys-infrastructure/surveys-mid-page.png`
was visually inspected: Lions blue controls, host font, focused comment field and
acknowledged save status render without clipping. The test asserts theme tokens
and no horizontal overflow. This is not a full accessibility audit. SurveyJS
fontless CSS uses host fonts. Browser rendering is the current baseline; the
independent packed demo, configurable translations and SSR evaluation remain open.
No editor, analytics, exports or entire work-package acceptance is claimed.


## Expanded boundary comparison

The comparison now includes 32 cases: the original seven plus short/long text
length, numeric/date bounds, required radio/dropdown, checkbox cardinality and
required matrix boundaries. `./leonaid test-surveys-core` passed all 32 actual
SurveyJS/runner versus Python comparisons, 16 Python tests and three queue tests.
The package TypeScript check also passed.

The expanded tests exposed four differences, retained as regression cases:
SurveyJS's native input constraints did not reject programmatically supplied
text beyond maxLength or checkbox selections beyond maxSelectedChoices. The
runner model factory now adds completion validation for those upper bounds.
The server previously allowed an empty checkbox answer at completion despite
minSelectedChoices; it now rejects completion while still accepting partial saves.

These results cover the enumerated boundary fixtures, not arbitrary SurveyJS
JSON or all profile semantics. Minimum text lengths, Unicode boundaries,
conditional-expression combinations and malformed inputs still require expanded
coverage before 010.2, 010.3 or 010.A1 can be checked. Comparing runner validation
includes our explicit model hooks; it is not a claim about bare SurveyJS behavior.

`./leonaid test-surveys-runner` then rebuilt the corrected model/backend in
`leonaid-surveys-833458328-15993`: real API/database contracts passed and all
three Chromium browser tests passed in 10.8 seconds. This regression run uses
the original two survey examples; the additional boundary comparison runs in
actual library/domain runtimes, not as 32 separate HTTP scenarios.

The first regression wrapper exited 127 after successful tests/teardown because
the CLI script was edited while the shell was running it. A repeat against the
unchanged CLI, project `leonaid-surveys-833458328-16951`, passed all three browser
tests in 12.5 seconds. The first wrapper exit is not treated as a passing gate.

A direct SurveyJS 3.0.3 metadata probe also confirmed that a question-level
`minLength: 3` is discarded during serialization and a one-character answer is
accepted by bare SurveyJS. Explicit client mapping for that profile rule remains
required and is not covered by the newly passing upper-bound checks.


## Minimum length, Unicode and compound conditions

The shared fixture set now contains 82 cases. `./leonaid test-surveys-core`
passed all actual runner/SurveyJS-versus-Python comparisons, 22 Python tests and
three save-coordinator tests. Strict mypy for the validator and package TypeScript
checking passed. This extends, rather than replaces, the earlier boundary proof.

Observed upstream semantics and implementation:

- Question-level minLength is mapped to SurveyJS's native TextValidator when the
  runner model is created; its absence from SurveyJS question metadata no longer
  silently disables the minimum. Optional empty input remains allowed.
- Text length uses UTF-16 code units in both runtimes, matching native browser
  maxlength. A supplementary emoji occupies two units; no normalization or
  truncation is performed by the server. Invalid Unicode scalar input is rejected.
- String equality/inequality and contains conditions are case-insensitive, matching
  SurveyJS's default. Numeric comparisons, empty/notempty, all/any combinations
  and nested parentheses are exercised by the new fixtures.
- Publication rejects properties that do not apply to the question/input type,
  including checkbox inputType=number, which previously could select the wrong
  validation branch. Rating scales are bounded to at most 100 options to prevent
  oversized controls. Zero maxLength/maxSelectedChoices use the bounded profile
  default rather than prohibiting every nonempty response.

The remaining parity audit still includes page-level/chained hidden relevance,
coercion edge cases and exhaustive malformed-definition coverage. SURV-010 is
not fully accepted by these additional cases alone.


Live proof for this increment: `./leonaid test-surveys-runner`, isolated project
`leonaid-surveys-833458328-20462`, passed real migration/API/PostgreSQL contracts
and four Chromium tests in 16.0 seconds. The additional browser test publishes
`validation-boundaries.json` through the real authoring API. It verifies a visible
minimum-length error, recovery after correction, uppercase YES activating the
persisted conditional question, and emoji input replacing and removing its hidden
follow-up. A direct authenticated response request with four UTF-16 units against
a three-unit maximum returns 422 and leaves both revision and answers unchanged.
The valid three-unit emoji/text answer then completes through the actual UI.

The comparison verifier now also independently validates every definition before
comparing answers and rejects missing, stale or duplicate named fixture results.


## Hidden-page chains and canonical restoration

Baseline `28b8a89`. The actual SurveyJS 3.0.3 probe exposed a missing case:
`clearInvisibleValues = "onHidden"` leaves answers intact when the containing page
becomes invisible. A later page referring to one of those answers stayed visible,
and reopening the first page reused stale values. The shared model factory now
uses `onHiddenContainer`, so editor preview and public runner agree on page-level
cleanup as well as question-level cleanup.

SurveyJS also defers initially hidden values until completion. The new
`restoreSurveyAnswers` helper normalizes empty/null/empty-array values before
loading and clears invisible question/container answers in questionnaire order.
The supported profile only permits preceding-answer references, so that ordered
pass also clears downstream branches. The helper is used for initial restoration
and acknowledged server snapshots; existing save-event suppression remains active.
No server validation rule was weakened and no dependency was added.

The shared comparison now has 88 named fixtures. Six new cases in
`validation-cases.json`, using `conditional-pages.json`, cover complete visible
chains, hidden pages with stale answers, hidden invalid values, missing/empty
required details and incomplete downstream answers. Expected canonical answers,
visible question IDs and completion validity are explicit. The verifier compares
actual server-cleaned snapshots and actual model data rather than using obsolete
raw answers for valid-state relevance; invalid-input visibility remains diagnostic.
Duplicate client-result names now fail rather than being overwritten in a map.

`./leonaid test-surveys-core` exited zero: 88 actual SurveyJS/Python comparisons,
23 Python tests and three save-coordinator tests with 17 assertions. The earlier
new empty-detail case failed until empty values were normalized before model
loading; SurveyJS's clearValue does not remove that already-empty representation.
Web/package TypeScript and Ruff checks for the changed Python tools passed in
pinned runtimes.

Live runner proof: `./leonaid test-surveys-runner`, project
`leonaid-surveys-833458328-59796`, passed all five Chromium scenarios in 19.7s
following real migration, API/PostgreSQL foundation and response-contract checks.
The new “hidden pages clear chained answers through edits, direct saves and
restoration” test fills a four-page chain, returns to the initial answer, hides
both dependent pages and verifies persisted cleanup. A direct PUT containing
stale hidden answers is accepted only after server cleanup; the stored snapshot
contains neither stale branch. Reload restores the last page with zero PUTs,
reopening the branch produces empty required fields, and completion stores only
fresh branch answers plus the preserved closing answer. All API writes are real;
no persistence or authorization endpoint is mocked.

This closes the specified browser verification scope of **010.T2** together with
the already-passing “acknowledged text survives closing mid-page and hidden follow-up
is removed” test (010.A3/010.A4), which checks no-blur saving, a fresh browser
context, back/forward navigation and reload. It does not establish all malformed
input/coercion parity or select the final validation architecture: 010.2, 010.3,
010.T1 and 010.A1 remain open.


A separate read-only probe identified the next unresolved parity boundary:
programmatic `model.data` can contain boolean/object values in text/number fields,
a string for a numeric choice, duplicate checkbox values, or an invalid ISO date
while SurveyJS `validate()` returns true for those optional questions. The server
already rejects these supplied nonempty values. This is not permission to weaken
server validation or evidence of full parity; additional client profile checks
and named negative fixtures are required before 010.A1 can be checked.


Editor regression for the shared factory change: `./leonaid test-surveys-editor`,
project `leonaid-surveys-833458328-60609`, passed all seven Chromium scenarios in
1.2 minutes. This includes both sample questionnaires, guided preview, keyboard
focus, import preservation and draft recovery. No new layout or theme claim is
made by this model-only regression. Both live commands used fresh isolated
volumes/networks and no host ports; both commands exited zero with verified
teardown. Raw artifacts remain local and ignored. 010.T2 is checked against this
commit's runner/fixture changes and the linked existing 010.A3/010.A4 evidence.

## Strict answer types and matrix completion

Implementation increment for 010.3 / 010.T1, based on `b86129b` plus this
commit's changes. Full 010.A1 acceptance remains open.

The shared model now validates actual answer types against the initial profile:
text/comment, finite numbers, canonical dates, typed choices, unique checkbox
values, rating bounds/steps and matrix rows/cells. Checks use the original
question definition and raw model value rather than SurveyJS's potentially
coerced validation-event value. Select questions no longer silently discard
unknown supplied choices during validation; explicit guarded hidden-answer
cleanup retains the existing question/page relevance behavior.

Two server defects were corrected: checkbox values `1` and `1.0` count as a
duplicate, and an empty required matrix cannot complete even when not every row
is mandatory. Partial empty matrices remain saveable. No dependency was added.

| Task | Acceptance scope | Test evidence | Result |
|---|---|---|---|
| 010.3 | Supplied types, incomplete versus invalid values, hidden cleanup; part of 010.A1 and existing 010.A2/010.A4 | `validation-cases.json`, actual model comparison, runner scenarios below | Implemented increment; full condition parity open |
| 010.T1 | Shared type/choice/matrix fixtures and real rejected writes | `tools/surveys/parity.mjs`, `parity.py`, `surveys-runner.spec.mjs` | Listed checks pass; full work-package test task remains open |

`./leonaid test-surveys-core` exited zero with 168 actual SurveyJS/Python
comparisons, 23 Python tests and three save-coordinator tests (17 assertions).
The 80 additional fixtures cover required and optional invalid types, invalid
dates, numeric-string choices, duplicate selections and matrix constraints.
Nine optional-invalid cases require the invalid value to remain present and
completion to fail; silently deleting it cannot pass. Model answers are now
captured **after** `validate()` to include any validation-time mutation.

`./leonaid test-surveys-runner` exited zero in isolated project
`leonaid-surveys-833458328-63646`: six Chromium scenarios passed in 20.9s,
following actual migrations, API/PostgreSQL foundation and response-contract
checks. In “forged answer types cannot advance persisted state and matrix
completion requires correction”, nine direct invalid answer payloads and a raw
JSON `[1,1.0]` selection receive HTTP 422 without changing stored answers or
revision. Saving an empty matrix succeeds as partial; completion fails without
changing the revision or setting completed. After reload, the actual UI shows
the matrix error, accepts row corrections and completes with the exact expected
server snapshot. Existing no-blur, offline/reconnect and chained-hidden-page
journeys also pass. The command published no host ports and verified teardown.

Web/package TypeScript, Ruff and strict mypy for the changed server validator
passed in pinned runtimes. Browser runs use the pinned images in
`infra/locks/images.env`, including SurveyJS core/React 3.0.3 from the lockfile.
Fixtures are synthetic; raw browser traces remain ignored local artifacts.

Remaining limitation confirmed by a separate actual-model probe: SurveyJS
compares a valid text answer `"1"` equal to the numeric literal `1` and greater
than `0`; the Python condition evaluator currently uses stricter types. It also
supports lexical string ordering that the current Python candidate does not.
These are unresolved relevance differences, not evidence that all condition
semantics pass. 010.2, 010.3, 010.T1 and 010.A1 therefore remain unchecked.

The shared-model editor regression also passed: `./leonaid test-surveys-editor`,
project `leonaid-surveys-833458328-65127`, seven Chromium scenarios in 1.1 minutes,
exit zero with verified teardown and no host ports. This covers both sample
authoring journeys, keyboard/preview accessibility, persisted structural edits,
safe import/publication rejection and draft-save recovery. It establishes no
additional mobile/theme or full-profile compatibility claim.

## Isolated validation candidate selection

Task **010.2** implementation selection, based on `6396f5b` plus this commit.
The linked **010.A1** acceptance remains open; no new actual-API or browser
integration acceptance is claimed by this comparison.

`./leonaid test-surveys-validation-candidate` executes three separate processes
in pinned Docker runtimes: Python approves every fixture definition using the
real capability validator, Bun evaluates the same definitions/answers through
the new shared-Core candidate, and Python compares explicit expected results
and the existing Python answer validator. The command exited zero for 192 cases.
It uses ephemeral containers without published ports or persistent services.

The candidate in `packages/surveys/src/validation-candidate.ts` shares the model,
restoration and answer checks used by the runner. It returns partial validity,
complete validity, cleaned answers and relevant question IDs, and disposes every
model. It is not exported as an untrusted-definition API and is not called by
the production backend yet. A `complete` flag on profile answer validation lets
partial responses omit required answers, minimum selection counts and required
matrix rows, while still rejecting malformed supplied values. Browser default
completion behavior is unchanged.

| Task | Required acceptance | Named scenarios / assertions | Delivery and remaining gap |
|---|---|---|---|
| 010.2 | 010.A1 | `validation_candidate.py`: all 168 existing cases plus 24 `candidate_*` cases in `condition-candidate-cases.json`; compare validity and exact snapshots, with explicit expected visible IDs | Comparison and JS selection delivered; real adapter integration still open |

New scenarios include numeric text, quoted numeric literals, lexical strings
and ISO dates, numeric/string contains, empty matrix, zero versus empty,
case-insensitive equality and combined conditions. Each is run with and without
its follow-up answer. Explicit expectations prevent a comparison from blessing
two implementations that both produce the wrong result. The verifier requires
the exact expected mismatch modes per case; unexpected differences or vanished
known differences fail and require review.

Observed result: 27 Python mode/snapshot differences across the new cases.
Eighteen are cleaned-snapshot differences with supplied follow-ups; nine are
completion differences when required follow-ups are missing. The Core candidate
retains the relevant supplied follow-ups and rejects their absence at completion.
The Python candidate incorrectly hides those questions. Aligned cases such as
zero/notempty, case-insensitive equality and nonnumeric text remain controls.
This evidence selects the shared-Core adapter in DECISIONS.md. It does not prove
adapter availability, failure atomicity, deployment or all malformed definitions.

Regression: `./leonaid test-surveys-core` exited zero (168 comparisons, 23 Python
tests, three coordinator tests / 17 assertions). Package TypeScript checking
also exited zero. Tests ran with Bun 1.2.19 and the pinned Python image from
`infra/locks/images.env`, and SurveyJS Core 3.0.3. No production container or
other worktree network was altered. The comparison JSON remains a synthetic,
ignored local artifact reproducible with the command above.

## Shared-Core backend integration

Tasks **010.3**, **010.T1** and criterion **010.A1** are accepted for the bounded
initial-v1 profile, based on `fb912b2` plus this commit's integration and tests.
This supersedes earlier statements in this historical proof that the adapter
was only a feasibility process. Other work packages remain open.

`AsyncpgSurveyRepository` now awaits the private Core adapter inside the existing
save/completion transaction, after identity, lifecycle and revision checks.
Python validates the stored immutable definition against the capability allowlist
and rejects unknown/oversized answers before calling the service. The service
uses the same model, restoration and answer checks as the browser. Invalid
answers produce HTTP 422; connection failure, timeout or a malformed adapter
contract produces HTTP 503 without a database update. No fallback to the
known-divergent Python answer evaluator is allowed. That evaluator remains only
as a regression/comparison reference.

The new Docker service runs pinned Bun 1.2.19, with only the bundled SurveyJS
Core 3.0.3 application dependency. It uses private `core-data`, no host port,
a read-only filesystem, non-root user, dropped capabilities, one CPU and 256 MiB
memory limits. The service bounds request bodies at 600,000 bytes; the host
retains separate 262,144-byte definition/answer limits and three-second HTTP I/O
timeouts. Core diagnostic logging is suppressed because it can contain answer
values. The built `/app` contained the 2,216,485-byte JS bundle and MIT notice
file, with no stylesheet/font assets. A single `docker stats` sample showed
28.56 MiB / 256 MiB and 0.09% CPU; this is an observation, not a load benchmark.

| Task / criterion | Named proof | Result |
|---|---|---|
| 010.3 / 010.A1, 010.A2 | `validation_live.py cases`, all 192 named fixture cases | Real publication, participation, partial save, persisted cleanup and completion behavior match expected outcomes; rejected writes preserve DB state |
| 010.T1 / 010.A1 | `test-surveys-validation-candidate`, 192 approved cases | Exact Core expectations pass; the old Python candidate's 27 differences remain explicitly diagnosed |
| 010.T1 / 010.A1 | `test_malformed_definitions_fail_closed`, `test_misapplied_properties_cannot_change_validation_branch`; existing [SURV-040 import/publication proof](SURV-040.md) | The unchanged host allowlist rejects unsupported definitions independently of the renderer, including direct publication attempts |
| 010.T1 / 010.A2, 010.A5 | `responses.py` and runner timeout/resume scenarios | Incomplete versus invalid answers, real idempotent writes, terminal completion and same-participation timeout resumption pass |
| 010.3 / 010.A2 | `validation_live.py unavailable/recover`, actual container stop and pause | Save and completion return 503; answers, revision, status and answer/completion timestamps are unchanged; exact save retry succeeds once after restart/unpause |
| 010.3 / 010.A4 | New numeric-text browser scenario plus existing hidden-page chain scenario | Relevant answers persist, hidden answers are removed, restoration stays correct, and reopening requires a fresh answer |

Final live command: `./leonaid test-surveys-runner`, project
`leonaid-surveys-833458328-71137`, **exit 0**, seven Chromium scenarios passed in
31.3 seconds, after migrations, foundation, response contracts, 192 condition/
answer API cases and both stopped/paused adapter recovery sequences. All API
and persistence paths are real. The fixture runner covers the 168 established
answer regressions plus 24 explicit condition cases; baseline expectations use
the previously compared Python results, while condition expectations are explicit
golden data. Invalid partial states are rejected before they can be persisted;
valid partial states are checked in PostgreSQL and against completion results.

The new E2E “numeric text conditions retain required follow-ups through actual
saves and reload” enters `"1"`, reloads the required follow-up, proves the empty
answer blocks completion, saves and restores a supplied detail, switches to
`"2"` and verifies persisted removal, then returns to `"1"`, supplies fresh text
and completes with the exact expected server snapshot. The other six scenarios
cover infrastructure, no-blur save/fresh-context resume, offline reconnect,
Unicode/minimum length, chained hidden pages and forged answer types/matrix
correction. Successful teardown verified removal of this project's containers
and volumes. A read-only log check after the API/failure scenarios confirmed
empty validator stdout/stderr; this is not a claim about all application logs.

Two preceding runs failed and were corrected: project `69405` failed its
IPv6 `localhost` healthcheck although IPv4 responded; the check now uses
`127.0.0.1`. Project `70135` passed the API and outage checks but the new browser
test read its participation ID before startup completed; it now waits for the
rendered source input and asserts the ID exists. Those runs do not count as
successful gates. Their isolated resources were cleaned up; the final run above
is the acceptance evidence.

Additional current checks passed: `./leonaid test-surveys-core` (168 legacy
comparisons, 23 Python tests, three coordinator tests / 17 assertions),
`./leonaid test-surveys-validation-candidate` (192 cases), Ruff for the changed
Python files and strict mypy for the new adapter. No commercial dependency was
introduced and our own license remains UNDEFINED. Runtime capacity testing,
complete product journeys, packed independent consumer, analytics and exports
are still tracked by their respective open work packages.
