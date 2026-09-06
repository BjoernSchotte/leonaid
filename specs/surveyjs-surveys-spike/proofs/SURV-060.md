# SURV-060 — Member module and scoped management

Baseline `c75b8c7` plus this commit's module, API/client and browser changes.
This delivers the member navigation, lifecycle and timeout UI; invitations,
complete capability coverage and test-participation isolation remain open.

## Task ledger

| Task | Criteria | Delivery / named evidence | Remaining acceptance |
|---|---|---|---|
| 060.1 | A4, A5 | `apps/web/src/surveys.tsx`, generated client, scoped list/summary and action creation; `surveys-module.spec.mjs` | Delivered; complete persona coverage and new-versus-existing participation/test-data UI evidence remain open |
| 060.2 | A1, A4 | Existing policies now govern lists/counts, summary capabilities, action linking and hidden publish controls; `module.py seed` | Aggregate/export/invitation/deletion capability matrix is not complete |
| 060.3 | A2, A3 | Existing anonymous respondent path only | Attributable invitations and Mailpit delivery remain open |
| 060.4 | A5 | No completion claim | Preview/test participation isolation remains open |
| 060.T1 | A1, A2 | Real member list/count/search/pagination and action-scope negative scenarios | Full capability and invitation coverage remain open |
| 060.T2 | A3, A4, A5 | Admin lifecycle/settings and mobile designer browser scenarios | Invitation, timeout snapshot effect and test-data exclusion journeys remain open |

## Behavior and boundaries

Authenticated members receive an Umfragen navigation entry. This does not give
access to other backoffice areas or anyone else's survey. The existing default
redirect for purely operational members remains in place outside survey routes.
A unit test verifies their only web navigation entry is surveys.

GET `/api/v1/surveys` supports status, literal title search and offset pagination
(50 results per page). Authorization is applied in SQL before count/pagination;
returned rows are also checked against the domain capability function. A
repeatable-read transaction keeps the count and page consistent. The response
includes only actions the member can manage as creation choices. GET summary
returns current capabilities and rejects inaccessible resources. The host uses
GET/list capabilities for controls and refreshes summary after mutations.

Creating a standalone survey assigns its creator as owner. Creating an
action-linked survey checks actual action management rights and action existence
before writing. Explicit survey grants do not bypass membership scope on an
action-linked survey. A design-only member can open the editor, but its publish
control is absent and the server independently rejects publication.

The neutral editor's optional `canPublish` flag controls presentation only; it
defaults to true for existing hosts. Optional `onSaveStateChange` reports its
save state. LeonAid uses that signal to disable lifecycle/settings actions while
the draft has unacknowledged changes. Backend authorization remains mandatory.

The member UI provides search/status filters, creation/action selection,
publication through the editor, end/archive/unarchive/trash/restore controls,
survey timeout override/inheritance and administrator-only global timeout forms.
Trash uses an inline consequence/confirmation step. Closed surveys do not mount
an editable draft, and restoration explicitly remains closed.

## Integration and browser evidence

`./leonaid test-surveys-lifecycle` succeeded as
`leonaid-surveys-833458328-88804`, exit **0**. The real stack passed its database
foundation, response contract and existing 25 lifecycle/action pair checks,
including publication/closing races, immutable versions and duplication.

`tools/surveys/module.py seed` created a real member, session, action and three
synthetic surveys. It proved:

- A standalone design grant exposes exactly one survey and only the design
  capability; private title search returns zero authorized results.
- A grant on an action-linked survey initially exposes nothing without action
  membership. After adding actual membership, the list contains exactly the two
  authorized surveys, while action-creation options remain empty for an acquirer.
- Counts remain authorization-filtered across offsets/status filters; negative
  offsets fail validation. A forbidden action-linked creation writes nothing.
- Global settings, foreign summaries, publication and trash are rejected for
  the unauthorized member through actual API calls.

Three Chromium scenarios passed through the real services: the infrastructure
journey plus these two tests in `tests/e2e/surveys-module.spec.mjs`:

1. `member manages lifecycle and timeout through the real module` (1440 × 1000)
   navigates from the main sidebar, changes/restores the global timeout, creates
   an action-linked survey, saves its override as three seconds, publishes, ends,
   archives, trashes and restores it. Reload retains ended status and no editor;
   the public API rejects access and the public page has no start control.
   Search/status filtering then finds the correct ended survey.
2. `designer sees scoped surveys without publish or delete controls on mobile`
   (390 × 844) sees only the two granted surveys, no global settings and no
   publish/trash controls. A direct publication request is rejected, and direct
   navigation to a foreign survey renders an error without an editor.

`module.py verify` then inspected PostgreSQL: the browser-created survey was
ended, retained the selected action ID and three-second override, and the global
default was restored to 1800. The successful harness verified cleanup of its
own containers/volumes/networks; seven unused explicit subnets and no host ports
kept it separate from other worktrees.

The first run (`…-88260`) passed backend checks and the mobile designer journey
but failed selecting the action with an exact label locator. Its trace confirmed
the intended UUID and the rendered combobox. Selecting by accessible combobox
role/name fixed the test; the repeated full run passed. The failed run is not
acceptance evidence.

## Visual review

Inspected the actual synthetic desktop lifecycle and mobile designer captures.
The lifecycle status/actions and closed-state explanation were readable; the
mobile controls wrapped without clipping in the captured state. This is not a
claim of every mobile/dark-mode/editor state or full accessibility acceptance.

![Closed lifecycle state](assets/SURV-060-lifecycle.png)
![Design-only mobile view](assets/SURV-060-designer-mobile.png)

## Supporting checks

Web TypeScript and Mypy on the four changed application source files passed.
Ruff passed on changed Python source and fixture files. The identity, policy and
migration unit selection passed 32 tests; the OpenAPI policy suite passed four.
The generated OpenAPI/client includes the previously delivered timeout APIs.

The frontend transport check initially rejected the independent demo's own
backend fetch. The corrected check exempts only its two fixed local routes in
the exact demo client file; negative fixtures still reject LeonAid API calls,
other routes and the same direct fetch from a regular web client. The independent
demo must not acquire a LeonAid-client dependency merely to satisfy this check.

`./leonaid test-surveys-package`, project `surveys-package-833458328-88872`, exited
zero: actual packed installation, permissive bundle/notice inspection and both
browser phases passed (2.9s and 893ms) with real restart and cleanup. The new
optional editor props do not enter the respondent bundle.

`./leonaid test-surveys-editor`, project `leonaid-surveys-833458328-89326`, exited
zero: all seven Chromium scenarios passed in 1.2 minutes, including both complete
sample authoring journeys, keyboard/accessibility checks, JSON import and
interrupted-save/two-tab draft recovery. Its isolated resources were removed.
The complete SURV-060 work package remains open.
