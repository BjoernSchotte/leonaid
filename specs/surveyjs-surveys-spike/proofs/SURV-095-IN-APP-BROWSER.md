# In-app browser functional proof

The final walkthrough used the Codex in-app browser against a fresh isolated
HTTPS fixture on 2026-09-08. Only synthetic users, questionnaires, responses and
local Mailpit messages were used. The local CA was trusted in the macOS login
keychain; no certificate warning was bypassed. Source: `913c2f7` plus the
publication-refresh correction described below. Earlier observations of controls
alone are not counted as successful interactions.

## Executed scenarios

| Area | Actual action and observed result |
| --- | --- |
| Module and templates | Admin opened the empty module and created standalone surveys. The earlier walkthrough created the three-page Krapfentaxi template; the complete automated journeys additionally execute both Krapfentaxi and Golf templates at desktop and mobile widths. |
| Editor | Duplicated and removed a page, undid and redid changes, reordered pages with buttons, Enter and a real mouse drag. Renamed a question, made it required, duplicated it and moved it to another page. Saved the result. |
| Authoring conditions | Added an equality rule in the visual editor, published it, entered the matching answer as a participant and observed the second page become available. |
| JSON | Invalid syntax produced a diagnostic. Exported the authored JSON, parsed the download, imported the same definition and saved it. An imported upload question was retained with a compatibility warning; publication was rejected by the server. Undo restored the supported questionnaire. |
| Publication | First publication changed draft to active. Version 1 and subsequently Version 2 became selectable in analysis immediately, without a page reload, after the correction below. |
| Renderers and validation | Executed short text, comment, radio, dropdown, checkbox, 0–10 rating, number, date and fixed matrix inputs across two pages. Empty required fields blocked navigation. An out-of-range number blocked completion and focused the invalid field. |
| Autosave and resume | Waited for acknowledged saving, reloaded the participation URL and recovered the values. A previously answered conditional field was hidden and then shown again empty. |
| Partial responses | Configured a 30-second inactivity timeout before starting the participation. Analysis subsequently showed one partial response, zero completed responses and the expected saved values. The participant could still complete; a new analysis then showed zero partial and one completed response. |
| Analysis | Compared choice/multiselect distributions, NPS, numeric summaries, matrix row values and last-saved page with the entered answers. Expanded a chart's equivalent data table and checked its counts and percentages. |
| Raw answers | Selected the completed answer, opened its details and loaded its free text. Entered values were preserved; the hidden field was shown as unanswered. |
| Exports | Created and downloaded analysis PDF/XLSX and raw-response CSV/XLSX through the browser. Parsed every file; raw formats contain the synthetic text and typed values, aggregate formats exclude individual free text, and all omit the cleared hidden answer. The five PDF pages were rendered and visually inspected: readable tables, charts, page numbers and no clipping or overlaps. |
| Invitations | Sent a personal invitation through the UI to local Mailpit, opened its link, started a participation and navigated its conditional pages. Revoked it in the admin UI; a subsequent completion attempt was rejected. No external SMTP delivery was used. |
| Authorization | Logged in through the normal email-code flow as a separate ordinary member. Its list contained no foreign surveys, and direct access to the admin's survey returned “Umfrage nicht gefunden.” |
| Global settings | Saved retention periods of 365/30 days and a 120-second default inactivity timeout; all three values survived reload. The test did not wait for retention erasure. |
| Scheduled end | Saved a future local end time through the native date control. After the deadline, reloading showed the survey ended automatically. CUA fill alone did not trigger React's date change; a native arrow-key edit did. No application change was needed. |
| Lifecycle | Ended, archived and moved a survey to trash. Inspected the explicit permanent-erasure confirmation and cancelled it. Restored the survey and confirmed it remained ended, with participation closed. |
| Responsive and keyboard | At 390×844 the matrix rendered vertically, with visible controls and full-width navigation. Desktop renderer layout was also inspected. Operated ordering using Enter; the full keyboard/accessibility matrix remains covered by the existing automated editor suite. |

## Defect found and corrected

Immediately after publication, the analysis panel still said to publish a
questionnaire. It had mounted while the survey was a draft and retained an empty
version list. Both the analysis and export-only host branches now key their
component by survey ID and published-version ID. A publication therefore reloads
the available versions; unrelated survey changes do not reset the analysis.

The existing `surveys-journey.spec.mjs` now asserts that Version 1 is available
immediately after publishing, before any reload. All four complete Krapfentaxi /
Golf desktop/mobile journeys passed with this assertion via
`./leonaid test-surveys-e2e` (exit 0, 515.72 seconds). Web typechecking and the
container web build also exited 0. The manual walkthrough independently proved
both the first-publication and second-version transitions.

The fixture controller exited 0. Ten independent final inventories confirmed
no owned containers, volumes, networks or seven project image tags remained.

## Evidence boundaries

This walkthrough supplements, rather than replaces, the existing automated
contracts, permissions, expiry, concurrency, worker-failure, retention, permanent
erasure and recovery scenarios. These were not all manually re-created. In
particular, the manual permanent-erasure check covered confirmation/cancellation;
actual database/object erasure is verified by the complete automated journeys.
The downloaded PDF was newly rendered; prior export corpus proofs remain
historical evidence for their respective fixtures. Mobile review here is a
viewport check, not a physical-device performance claim.

[Structured observations and download hashes](assets/SURV-095-in-app-browser.json)
