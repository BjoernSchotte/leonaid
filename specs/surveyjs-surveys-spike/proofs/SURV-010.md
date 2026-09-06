# SURV-010 — Response persistence evidence

Date: 2026-09-06. Status: partial; browser autosave and full validation parity
remain open. This is not a completed survey module.

## Checked items: 010.1, 010.A2, 010.A5

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

Reproduce the comparison by running `tools/surveys/parity.mjs OUTPUT.json` in
the pinned Node container, then `tools/surveys/parity.py OUTPUT.json` in the
pinned Python container with `PYTHONPATH=/workspace/src`. Inputs are committed
in `tests/fixtures/surveys/validation-cases.json`; outputs stay local.

These seven cases do not establish parity for every initial capability, every
condition or every malformed input. The Python validator is still a candidate;
010.2, 010.3 and 010.A1 remain open pending the full comparison and selection.
No browser questionnaire runner, answer-event debounce, restart/chaos proof,
invitation implementation or full lifecycle UI is claimed here. Browser-based
mid-page abandonment and recovery remain separate required acceptance items.
