# SURV-040 — Initial visual editor evidence

Date: 2026-09-06. Status: implementation items 040.1–040.4 and scoped acceptance
040.A1–A5 / 040.T1–T2 proven. This does not complete the dependent package,
theme/mobile, validation or whole-spike work packages.

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


## Keyboard focus and accessibility verification

The [technical audit](SURV-040-AUDIT.md) records the baseline failure and scoped
follow-up. The editor now focuses a moved page/question's stable control after
keyboard reordering, focuses blocking validation and JSON errors, focuses the
preview heading on entry and restores its trigger on return. Preview disables
SurveyJS's competing automatic first-question focus and disposes its model when
closed. JSON errors are connected to the input with `aria-describedby` and
`aria-invalid`. Control borders use a configurable higher-contrast token and
buttons have a 44px minimum width as well as height. Focus indicators do not
transition in from zero width under host motion rules. Preview controls are
excluded from the editor's generic input/label/button styling. Its title event
handler selects semantic survey/page/question headings per model, without
mutating global SurveyJS settings.

`tests/e2e/surveys-accessibility.spec.mjs` traverses actual Tab order and uses
Enter, arrow keys, Space and keyboard text entry. It deliberately does not use
locator focus/click/fill/selectOption shortcuts. It creates a survey, edits and
duplicates questions, reorders questions/pages, adds a required choice and guided
conditional comment, corrects a server validation error, enters/responds to the
preview, returns, publishes and reloads. Persisted page/question order is checked
against the actual API, and page errors must remain empty. Focus targets and a
visible outline are asserted separately from the axe scans. A computed border
contrast assertion supplements axe's text/ARIA checks.

The repository already contains `@axe-core/playwright` and `axe-core` 4.12.1
(MPL-2.0) as host QA tooling. This work uses that existing external test harness;
it adds no dependency to the neutral package, copies no axe implementation and
ships no axe code with the editor/runner. The package's permissive runtime policy
and own UNDEFINED license decision are unchanged.

### Diagnostic run history

All projects below used fresh volumes, explicit unused subnets and no published
host ports. Earlier green runs did not close the acceptance gap while manual axe
findings remained unreviewed.

- `45978`: keyboard reorder lost its focus target; six other scenarios passed.
- `48621`: seven scenarios passed after focus management, but inspection exposed
  preview style leakage and unreviewed axe findings.
- `50032`, `50681`, `51910`: six scenarios passed; the immediate computed focus
  width assertion failed. Focused DOM identity alone did not prove a visible ring.
- `53125`: six scenarios passed; the test hung awaiting an animation's completion.
  The trace showed a focused page button with the correct 3px rule but active
  host-induced transitions. The unbounded animation wait was removed and focused
  targets now opt out of transitions.
- `54966`: all seven scenarios passed in 1.2 minutes, command exit zero with
  verified teardown. Full axe details then exposed a default SurveyJS title `div`
  with an unsupported accessible label, motivating the per-model heading fix.

Project names use the prefix `leonaid-surveys-833458328-`. Raw traces are local
and ignored; no session cookies or answer-bearing application logs are committed.

### Final verification and acceptance

Baseline `542d409` plus the source changes in this proof's commit were rebuilt by
`./leonaid test-surveys-editor` in project `leonaid-surveys-833458328-56489`.
The command exited zero: real migrations and API/PostgreSQL foundation passed,
all seven Chromium scenarios passed in 1.5 minutes, and owned containers/volumes
were removed and teardown verified. No host ports were published. Runtimes are
pinned by `infra/locks/images.env`; SurveyJS core/React are 3.0.3, Playwright is
1.54.1 and axe is 4.12.1. Web/package TypeScript checks exited zero in pinned Bun;
five editor tests passed with 33 assertions. `git diff --check` passed.

The [scan summary](assets/SURV-040-accessibility.json) records five states, each
with zero WCAG-tagged violations and 17 passing rules. Initial editor and question
properties had no incomplete rules. Error/reload states flagged arrow-only button
contrast; preview flagged contrast because of the SurveyJS background pseudo
element. No ARIA finding remains after the per-model semantic heading fix.

Manual review used the captured computed foreground, ancestor/pseudo background,
alpha and opacity values plus the rendered screenshots. There were no gradients
or intervening opacity on these final-state targets. Alpha was composited over the
observed surface before the sRGB relative-luminance contrast calculation:

| Reviewed target | Foreground / actual surface | Contrast |
|---|---|---|
| Enabled page movement arrows | `#172238` / white | 15.881:1 |
| Enabled question movement arrows | `#172238` / `#f5f7fa` | 14.797:1 |
| Survey/question titles and choices | `#1c1b20` / white | 17.115:1 |
| Page title | `#1c1b20` / pseudo surface `#edf9f7` | 15.888:1 |
| Survey description | `#1c1b20` at 0.6 alpha / white | 4.507:1 |
| Comment input text | `#1c1b20` / `#f5f5f5` | 15.698:1 |
| Next-button label | `color(srgb 0 0.17 0.47)` / white | 12.954:1 |

The description narrowly exceeds 4.5:1 in this exact theme; future theme changes
must recheck it. Enabled arrows also have explicit accessible action labels.
Disabled controls are visibly distinguished. The input-border token has 4.13:1
contrast on white and 3.85:1 on the editor canvas. These observations resolve the
listed incomplete findings for this fixture; they are not a WCAG certification.

Visual inspection of the [editor](assets/SURV-040-keyboard-editor.png) and
[preview](assets/SURV-040-keyboard-preview.png) found readable labels, correctly
aligned radio options and no clipped controls in this desktop layout. The preview
screenshot fast-forwards finite animations using Playwright's standard screenshot
option; it represents the settled state. Keyboard/focus assertions run against
the actual UI. Full mobile, zoom, screen-reader and all-theme proof stays open.

Acceptance traceability:

- **040.A4:** `surveys-accessibility.spec.mjs`, “keyboard authoring, recovery and
  preview have visible focus and accessible controls”, proves actual keyboard
  traversal, guided conditions, reorder focus, server-error correction, preview
  entry/return, publication and persisted ordering after reload; the manual
  observations above supplement the automated checks.
- **040.T2 / 040.A3 / 040.A5:** the same passing command includes both complete
  sample-authoring tests in `surveys-authoring.spec.mjs`, drag/structural editing
  in `surveys-editor.spec.mjs`, and undo/redo, interrupted save and two-tab recovery
  in `surveys-import-recovery.spec.mjs`. Their detailed assertions are documented
  in the preceding increments. No survey persistence/authorization endpoint is
  mocked. Only network delivery is deliberately interrupted in recovery tests.

040.A4 and 040.T2 are now checked. Broader profile validation, independent packed
consumption, theme/mobile work, analytics, exports and the other remaining plan
items retain their open status.
