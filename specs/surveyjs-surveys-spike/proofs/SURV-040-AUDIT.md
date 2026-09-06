# SURV-040 — Editor technical audit

Date: 2026-09-06. Baseline: `47d1fd1`. Scope: neutral editor in LeonAid,
desktop light mode; source review of performance, responsive and theme boundaries.
This audit is diagnostic. The existing implementation goal authorizes the follow-up
fixes; no new product scope or dependency is introduced. Ratings are review
judgments, not a WCAG certification or a measured performance benchmark.

## Anti-pattern verdict

Pass with limitations: the page outline, question canvas and property forms serve
distinct authoring jobs; no decorative metric cards, gradients or glass effects.
The fallback font and repeated outlined controls are generic and still need host
theme integration. The existing Lions design context remains the authority.

## Audit health score

| Dimension | Baseline score / 4 | Finding |
|---|---|---|
| Accessibility | 2 | Native controls and labels work; keyboard reorder loses useful focus and field borders are too faint. |
| Performance | 2 | Bounded history and debounce exist; complete definition copies also occur for save-status renders. No latency benchmark yet. |
| Responsive design | 2 | Breakpoints and 44px control heights exist; complete mobile/touch/zoom proof remains open. |
| Theming | 1 | Partial neutral tokens; host dark-mode/font mapping and several hard-coded colors remain. |
| Anti-patterns | 3 | Task-oriented layout, with generic fallback/control styling. |
| Total | 10/20 | Acceptable; significant follow-up remains. |

Four findings: P0 0, P1 2, P2 2, P3 0. Fix focus and non-text contrast first.
The final spike cannot claim all-theme/mobile acceptance from this desktop audit.

## Findings

### P1 — Focus is not managed across structural/view changes

Location at baseline: `packages/surveys/src/editor.tsx:325` (preview return),
`:371` (error), and page/question movement controls later in the same component.
The Chromium keyboard journey in isolated project
`leonaid-surveys-833458328-45978` failed immediately after moving question 2 up:
the moved question button was inactive instead of receiving focus. Source review
also finds no focus target when preview replaces the editor or an asynchronous
validation error appears. This makes a keyboard user search for their place and
complicates recovery. Relevant WCAG areas: 2.4.3 focus order and 2.4.7 visible focus.
Recommendation: `/harden` — restore focus to stable moved-item controls, provide
preview entry/return targets and focus blocking errors without changing tab order.

### P1 — Input boundaries have insufficient non-text contrast

Location: `packages/surveys/src/editor.css:34`–`:50` at baseline. The transparent
inputs on the white editor surface rely on a `#9da9ba` border: computed sRGB
contrast is 2.38:1. Button borders `#bac4d2` are 1.76:1. The field boundary falls
below the 3:1 non-text contrast threshold (WCAG 1.4.11), making it harder to locate
inputs. Recommendation: `/normalize` — expose a neutral control-border token with
a default that exceeds 3:1 on both white and canvas surfaces. Retain visible focus
and disabled-state distinctions. This contrast check is separate from axe.

### P2 — Neutral theme tokens are not fully mapped by the host

Location: `packages/surveys/src/editor.css:1`, `:103`, `:119` and
`apps/web/src/surveys.tsx`. Several surface/text colors are fixed and no
`--survey-*` overrides are supplied by the host. The editor remains light when
the surrounding host changes theme and does not inherit its font explicitly.
Recommendation: `/normalize` — wire semantic host tokens at the adapter boundary
and prove light/dark/system and adjacent host controls under SURV-020/C-15.
This remains separate from desktop-light keyboard acceptance.

### P2 — Save-status renders also copy the whole definition

Location: `packages/surveys/src/editor.tsx:64` and
`packages/surveys/src/editor-model.ts`'s document getter. Every status notification
rerenders the editor, clones the definition and scans compatibility even when no
answer definition changed. History is bounded but these copies still add avoidable
allocation. No user-visible slowdown has been measured. Recommendation:
`/optimize` — measure a maximum-profile fixture and cache snapshots/diagnostics by
history generation without exposing mutable history state.

## Positive findings and systemic follow-up

Native buttons, inputs, labels, details/summary, explicit movement controls,
status announcements and undo/redo provide a sound base. The new keyboard test
uses actual Tab/Enter/text entry, not programmatic focus or pointer shortcuts.
Its initial editor and question-property axe scans completed without WCAG-tagged
violations before the reorder-focus assertion failed. Real persistence, safe
preview validation and conflict recovery remain covered by separate browser tests.
Focus handling should be a shared editor behavior rather than separate ad hoc
fixes for each button. Theme values should remain host-supplied to preserve the
neutral package boundary.

## Recommended implementation order

1. `/harden` — stable focus after reordering, preview and validation errors.
2. `/normalize` — field/control border contrast; later complete host theme mapping.
3. `/optimize` — measure and address allocation costs before maximum-profile claims.
4. `/polish` — review rendered states after the functional fixes.

Re-run the keyboard/axe gate after fixes and record actual results in
[SURV-040](SURV-040.md). The existing goal already authorizes implementation;
this report does not introduce an approval stop.

## Follow-up disposition

The final `56489` isolated run passed all seven editor scenarios and both source
P1 findings are resolved for the desktop-light fixture: stable focus targets,
immediate 3px focus rings and stronger configurable control borders are verified.
Browser review additionally found and fixed preview style leakage and default
SurveyJS title semantics. See [the final verification](SURV-040.md#final-verification-and-acceptance)
for the incomplete-rule review, contrast calculations and screenshots.

The baseline scores above are retained as the diagnostic snapshot; no full-product
rescore is claimed. Theme/mobile boundaries and allocation measurement remain open
under the original plan, and this is not a screen-reader or WCAG certification.
