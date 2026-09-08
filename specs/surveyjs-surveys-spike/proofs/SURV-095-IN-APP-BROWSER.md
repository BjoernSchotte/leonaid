# In-app browser functional proof

This proof records the live inspection in the Codex in-app browser against the
isolated HTTPS fixture on 2026-09-08. Only synthetic data was used.

## Passed scenarios

- The authenticated System-Admin can open **Umfragen**, see the empty state,
  use the status filter (Alle, Entwurf, Aktiv, Beendet, Archiviert,
  Papierkorb), and create a standalone survey.
- The creation flow offers the Krapfentaxi and Golfturnier templates. The
  Krapfentaxi template created a three-page draft without recipients or prior
  answers.
- The editor exposed page ordering and movement, page duplication/removal,
  question movement between pages, question duplication/removal, the SurveyJS
  question types (short/long text, single choice, dropdown, multiple choice,
  rating, matrix), required state, visibility-rule entry, numeric/date input
  modes, progress placement, undo/redo controls, JSON import/export controls,
  save, preview and publish.
- Preview showed the three-page progress tabs, required-question validation,
  back/forward navigation and the configured rating/single-choice/text
  questions. Preview explicitly states that answers are not saved.
- Publishing changed the survey from Entwurf to Aktiv and exposed a public
  link. Closing changed it to Beendet and archiving changed it to Archiviert.
- A public participant opened the link, began a participation, selected a
  rating, saw **Alle Antworten gespeichert**, reloaded the same participation
  URL and recovered the selected rating on page one. This is direct in-app
  evidence of server-backed partial persistence and resume.
- Analysis creation exposed version, participation-status, date-range and
  answer-source filters. The result included counts for in-progress,
  partial and completed participation, per-question validity/unanswered
  counts, rating statistics, NPS fields, last-saved-page and table toggles.
  An analysis Excel export reached **Bereit zum Herunterladen**.

## Not closed by this run

The disposable fixture did not provide enough data or a second role to prove
all authorization boundaries, invitation delivery/expiry/revocation, timeout
expiry, completed-response statistics, every question renderer, JSON
round-trip/import diagnostics, conflict handling, actual downloaded CSV/XLSX/PDF
contents or rendered PDF review, responsive layout, keyboard-only operation,
or permanent deletion. These remain explicit follow-up checks; no claim is
made for them here.

[Structured observations](assets/SURV-095-in-app-browser.json)
