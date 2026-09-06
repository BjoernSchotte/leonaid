# SURV-010 — Response persistence evidence

Date: 2026-09-06. Status: partial; full validation parity remains open. This is not a completed survey module.

## Checked items: 010.1, 010.4, 010.A2–A5

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
