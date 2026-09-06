# SURV-040 — Initial visual editor evidence

Date: 2026-09-06. Status: partial; implementation item 040.1 delivered.
Its broader work-package acceptance criteria remain open.

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
publication validation remains authoritative. The initial UI does not yet expose
publication, so no unsupported definition can bypass server validation here.

Three Bun tests (16 assertions) passed in the pinned runtime: stable identity and
unknown-data preservation, correct duplicate reference mapping/undo/redo, and exact
operation replay before newer edits after an uncertain save. Package and host
TypeScript checks and the permissive dependency inventory passed.

## Remaining acceptance

The full Krapfentaxi and golf authoring/publishing journeys, guided conditions,
complete bounds/property panels, preview, safe JSON import/export, complete
keyboard/accessibility and mobile/theme acceptance, conflict/reconnect browser
coverage, navigation/list integration and the packed independent consumer remain
open. No complete work package or full editor parity is claimed.


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

040.1's implementation checkbox records the delivered structural editing
operations. 040.A1, A3 and A4 remain open until their full definition roundtrip,
both complete questionnaire/publish journeys and keyboard/error/a11y scope are
proven. This distinction follows the plan's separate implementation/acceptance
tracking; no whole editor work package is marked complete.
