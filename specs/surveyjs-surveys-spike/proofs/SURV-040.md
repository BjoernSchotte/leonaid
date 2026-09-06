# SURV-040 — Initial visual editor evidence

Date: 2026-09-06. Status: partial; implementation items 040.1–040.4 delivered;
040.A1/A2/A3/A5 and 040.T1 proven. Full keyboard/accessibility acceptance
040.A4 and its combined browser verification task 040.T2 remain open.

## Implemented surface

The neutral package exports SurveyEditor and a separate scoped editor stylesheet.
It consumes Draft/AuthoringAdapter contracts and imports no LeonAid code. The
LeonAid host supplies the generated client on protected `/admin/surveys/new` and
`/admin/surveys/<id>` routes. Creation and draft saving use the real authoring API.
The static server route allowlist includes the new paths; the first browser probe
caught its former fallback-page behavior and that integration was corrected.

The initial UI implements page/question add, move, duplicate and remove operations,
HTML drag-and-drop plus explicit keyboard movement controls, stable IDs, basic
question properties and choices, undo/redo, 700ms revisioned draft autosave, visible
save errors and conflicts. It preserves unknown properties, keeps unsupported
question types read-only and does not import commercial editor code.

The history model remaps internal references when duplicating pages without
rewriting quoted literals. It keeps 100 in-memory edit snapshots; undo/redo is
saved as a new revision. Reordering may invalidate preceding-answer references;
publication validation remains authoritative. At that initial milestone the UI did not expose publication. The authoring
increment below adds it with the same authoritative server validation.

Three Bun tests (16 assertions) passed in the pinned runtime: stable identity and
unknown-data preservation, correct duplicate reference mapping/undo/redo, and exact
operation replay before newer edits after an uncertain save. Package and host
TypeScript checks and the permissive dependency inventory passed.

## Remaining acceptance

Complete profile/property compatibility, full keyboard/accessibility and
mobile/theme acceptance, navigation/list integration and the packed independent
consumer remain open. No complete work package or full editor parity is claimed.


## Live browser result

`./leonaid test-surveys-editor` passed against fresh isolated project
`leonaid-surveys-833458328-32618`. PostgreSQL migration/foundation passed, then
both Chromium tests passed in 13.8 seconds: the editor journey and existing
member/public infrastructure. No host ports were published. The preceding
selector failure was corrected to use the control's accessible combobox role;
it was not suppressed or skipped.

`tests/e2e/surveys-editor.spec.mjs` creates a real survey through the member UI,
adds a single-choice question, edits labels, drags questions to reorder them,
duplicates a page, undoes/redoes, reorders pages with the keyboard and reloads.
It then moves a question between pages, duplicates/removes it, restores it using
undo, reorders it with Enter on the movement button and removes/restores a page.
After each acknowledged save, real API reads assert persisted definitions, stable
IDs and choice data. No mocked draft API is used.

The local artifact `.artifacts/surveys-infrastructure/surveys-editor.png` was
visually inspected at 1440px width: page navigation, question canvas, property
panel and save controls are readable without overlap. This is desktop visual
review, not the complete mobile/dark-mode/accessibility acceptance.

At the structural milestone, 040.1's checkbox recorded delivery while 040.A1,
A3 and A4 remained open. The subsequent sample authoring proof below completes
A3; the full definition roundtrip and keyboard/error/a11y scope remain open. This distinction follows the plan's separate implementation/acceptance
tracking; no whole editor work package is marked complete.


## Complete sample authoring and validated preview

The next increment implements 040.2 and proves 040.A3. It adds guided preceding-
answer conditions (one all/any level), required flags, bounds, rating scales,
choice/matrix entry ordering and questionnaire presentation controls. Preview
first flushes the draft and validates the exact persisted revision through
`POST /api/v1/surveys/{id}/draft/validate`; only that validated definition reaches
SurveyJS. Authorization and survey state are checked before validation. No
participation adapter is attached to the preview. Publication retries reuse the
operation ID and revision after uncertain acknowledgement, locking edits until
that operation resolves.

`./leonaid test-surveys-editor` ran against fresh project
`leonaid-surveys-833458328-40403`: four Chromium tests passed in 37.8 seconds,
following real migration/API/PostgreSQL foundation checks. The command exited
zero and verified teardown of its own containers and volumes. No host ports were
published. The tests and implementation use SurveyJS core/react 3.0.3.

`tests/e2e/surveys-authoring.spec.mjs` creates both questionnaires entirely through
member controls, without entering JSON. Each has three pages and six questions:

- Krapfentaxi: required delivery rating, conditional improvement comment,
  required freshness choice, optional notes, required 0–10 recommendation scale
  and optional name with length limits.
- Golf: required three-by-three matrix, bounded multiple selection, conditional
  food comment, future-attendance dropdown, bounded handicap and date inputs.

Both journeys save, reject an unsafe presentation value before preview, correct
it, complete all preview pages, assert conditional follow-ups, and verify zero
participation requests. They then publish and inspect the real public definition
for version 1, page/question counts and key properties; a reload restores the
persisted title. The taxi journey drops the HTTP acknowledgement after the real
server commits publication, retries, and still receives version 1. The existing
structural editor scenario in the same run proves page/question reordering,
movement, duplication and undo/redo against persisted definitions.

The preceding run (`leonaid-surveys-833458328-39598`) had three passing scenarios
and one test interaction failure: SurveyJS's decorative checkbox intercepted a
pointer click aimed at its hidden native input. The final test uses Space on the
native checkbox and asserts its checked state; no forced click, mocked server,
skipped scenario or relaxed assertion was introduced.

Additional checks in pinned runtimes passed: package and web TypeScript checks;
three editor model tests (16 assertions); `./leonaid test-surveys-core` (82 actual
SurveyJS/Python comparisons, 23 Python tests, three save-queue tests with 17
assertions); `./leonaid test-surveys-dependencies` (MIT runtime dependencies,
OFL font inventory and four negative cases). The generated API contract includes
the validate-draft endpoint.

The web TypeScript configuration now skips external declaration checking because
SurveyJS 3.0.3's matrix renderer declaration has a nullable return incompatible
with its declared base method (TS2416). Application source remains strict. This
upstream declaration limitation is documented in the package README.

Local screenshots are `.artifacts/surveys-infrastructure/surveys-authoring-Golf.png`
and `surveys-authoring-Krapfentaxi.png`. The Golf screenshot was visually inspected
at 1440px: saved state, presentation controls and three-page outline are readable.
Full typography/theme, mobile and accessibility acceptance remain open.

At the sample-authoring milestone, 040.A1/A2/A4/A5 and 040.T1/T2 remained open
for their broader roundtrip/import, keyboard/error/accessibility and interrupted
draft-save scope. The import/recovery increment below resolves part of that scope.
The sample-authoring evidence does
not accept the entire editor work package or claim arbitrary SurveyJS support.


## JSON preservation, publication diagnostics and draft recovery

The import/recovery increment adds a bounded file/paste import and current-local-
state download. Applying imported JSON is a single undoable history change. The
parser rejects invalid root/page/question structures, non-finite numbers and
excessive nesting without replacing the existing document. Safe unknown JSON is
preserved rather than stripped. Compatibility notices identify root/page fields
and affected questions by path; unsupported question/options regions remain
read-only. Preview/publication still validate the persisted definition on the
server, which now identifies the affected page/question in validation errors.

Conflict recovery offers a download of local changes and an explicit discard-
local/load-server action. Loading resets edit history and the coordinator to the
server revision; it does not overwrite the winning server draft. An uncertain
network save retains its exact operation ID/payload until resolved before newer
edits can be sent.

The added test file is `tests/e2e/surveys-import-recovery.spec.mjs`. Its import
journey reads actual persisted definitions and downloaded JSON, including nested
unknown metadata and stable identities. It checks malformed JSON without a state
change, unsupported/unsafe publication errors, absence of external requests,
undo/redo of imports, reload, and successful publication after correction. Its
recovery journey commits a real save then drops the acknowledgement, blocks a
retry while a newer edit is made, reconnects, verifies exact request replay and
revision progression, checks undo/redo, and resolves an actual two-tab conflict.
No persistence or authorization endpoint is mocked.


Live verification: `./leonaid test-surveys-editor` passed all six Chromium
scenarios in 54.4 seconds against fresh project
`leonaid-surveys-833458328-44133`, following the real migration and
API/PostgreSQL foundation checks. The command exited zero, published no host
ports and verified teardown of its own containers and volumes. Both new scenarios use the real member UI and
backend; downloaded JSON and persisted server state are asserted, not inferred
from a success toast. The preceding run (`leonaid-surveys-833458328-43174`) had
five passing scenarios and one locator failure after filling the JSON textarea.
The corrected locator selects its accessible textbox role; the unchanged
assertions and complete import journey then passed.

The import roundtrip and two-tab conflict prove 040.A1. Unsupported metadata and
question properties, unsafe presentation, path diagnostics and successful
publication after correction prove 040.A2. Lost acknowledgement/replay, explicit
unsaved/error state, undo/redo and conflict resolution prove 040.A5. These checks
also satisfy the scoped integration verification task 040.T1. All four editor
implementation items are delivered; 040.A4 and 040.T2 stay unchecked until the
complete keyboard/error/accessibility journey is proven.

Supporting gates passed in pinned runtimes: `bun run typecheck:web`,
`bunx tsc --noEmit -p packages/surveys/tsconfig.json`,
`bun test tools/surveys/editor.test.ts` (five tests, 33 assertions),
`./leonaid test-surveys-core` (82 actual SurveyJS/Python comparisons, 23 Python
tests, three queue tests/17 assertions) and
`uv run --frozen ruff check src/leonaid/domain/surveys/validation.py`.
Each exited zero. No dependencies were added. Definitions used in the tests are
synthetic; raw browser traces remain in ignored local artifacts.
