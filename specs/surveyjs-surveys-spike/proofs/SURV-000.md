# SURV-000 evidence

Status: partial, 2026-09-06. Work package remains open.

## 000.A4 — Dependency admission gate

Passed `./leonaid test-surveys-dependencies` in the repository-pinned Bun
1.2.19 Docker image (exit 0). The command inspected the installed package
manifests and transitive dependency declarations:

| Package | Version | License |
|---|---|---|
| survey-core | 3.0.3 | MIT |
| survey-react-ui | 3.0.3 | MIT |
| react | 19.2.8 | MIT |
| react-dom | 19.2.8 | MIT |
| scheduler | 0.27.0 | MIT |

The actual survey-core font license file identifies OFL-1.1. Four negative
fixtures were rejected: prohibited Creator package, commercial license on an
otherwise approved package, unreviewed version, and unknown transitive dependency.
The new package remains private/UNLICENSED; the own-license decision remains
UNDEFINED. No Creator, Dashboard or PDF Generator package was installed.

This proves the initial dependency gate only. It does not establish the final
artifact's notices, future editor/chart dependencies, runtime UI behavior or
all of SURV-000. Those checks remain open. Package dependencies are locked in
bun.lock; adding the workspace required its manifest in all frontend Docker
build stages. Contracts are initial and have no persistence proof yet.

## 000.A2 — Clean real-service foundation

Passed `./leonaid test-surveys-infrastructure` (exit 0) on 2026-09-06.
A fresh per-invocation Compose project built the actual services, migrated an
empty PostgreSQL database through 0027, seeded a synthetic admin/session, and
verified a persisted survey response snapshot. Updating a published version was
rejected by PostgreSQL; deleting the synthetic survey removed its participation.
The actual API returned readiness and authenticated identity successfully.

Playwright Chromium then opened the member UI with that server session and the
public site through the real proxy, with no mocked API routes (one browser test
passed). The screenshot was inspected locally. This is host infrastructure
evidence, not an implemented survey editor or respondent journey. 000.A3 stays
open in that initial run; the subsequent failure-diagnostic proof below now accepts it.

The command removed its own containers and volumes and checked that none
remained. It published no host ports. The first attempt encountered exhausted
Docker automatic address pools; the runner now selects explicit /24 subnets
that do not overlap the current Docker inventory. It refuses existing project
resources and never prunes other projects. Concurrent subnet allocation can
still cause a safe startup failure; rerun selects another project/subnet set.

Additional checks: three domain boundary tests passed (timeout, restoration and
action-scoped grants); five existing migration/architecture checks passed.
SurveyJS core executed both questionnaire fixtures in pinned Node, proving
basic rendering-model conditions, required matrix values and numeric bounds.
This does not yet prove authoritative answer validation parity.

## Foundation browser failure diagnostics

**000.T2 / 000.A3 / 000.S4 are accepted.** Source: the commit introducing this
section, based on `fecfd78`. The rest of SURV-000 remains open.

`tools/surveys/foundation_acceptance.py` runs two independent fresh Docker stacks
through the existing infrastructure harness. Each migrates to current schema,
proves the database/real-API foundation, publishes the actual questionnaire
fixtures, and creates a separate ordinary account without a global administrator
grant. Chromium authenticates that account and verifies the member UI, public
homepage, and a real published Krapfentaxi survey shell with its title and start
button. Both frontends are reached through the actual proxy; there are no mocked
API routes. The context uses the pinned Playwright default viewport, 1280 × 720
(verified in its installed browserContext implementation). This is not an
accessibility or mobile visual review.

The second browser run deliberately fails an assertion whose received value
contains the actual temporary member-session token and a recognizable test marker.
The restricted reporter retains only status, approved completed-step names, test
file/line/column, error category and counts. Messages, snippets, stacks, titles,
stdout/stderr, attachments and trace contents are excluded. Foundation tracing is
disabled; the failure collector does not copy raw test-result files or screenshots.
Before retaining the JSON, it checks every actual session/fixture environment
value and the error marker against its bytes. Other survey test modes retain their
previous local diagnostic behavior and are not covered by this privacy claim.

| Run | Browser result | Command exit | Retained diagnostics and teardown |
| --- | --- | --- | --- |
| `leonaid-surveys-833458328-94006` | All three steps pass | 0 | No errors, credential scan passed, no owned containers/volumes/networks remain |
| `leonaid-surveys-833458328-94504` | All three steps pass, then deliberate assertion fails | 1 | Assertion location retained, raw error marker absent from command log, actual credential scan passed, no owned containers/volumes/networks remain |

The outer acceptance command exits **0** only after verifying both expected exit
codes, the three completed steps, one result per run, the safe report, the failure
location, and Docker teardown. An earlier infrastructure/setup failure cannot
masquerade as the intended browser failure. The stacks use distinct generated
project names, explicit unused subnets and no published host ports.

```sh
rtk proxy python3 tools/surveys/foundation_acceptance.py "$PWD"
```

The underlying commands are `sh tools/surveys/infrastructure.sh "$PWD"
infrastructure` and the same command with `infrastructure-failure`. The normal
`./leonaid test-surveys-infrastructure` entrypoint continues to run the positive
case. The pinned Playwright image runs Chromium 139.0.7258.5 / Playwright 1.54.1.
The API/worker and frontend images are built from this checkout with the pinned
repository toolchains. Ruff for the three Python files, shell syntax and diff
whitespace checks pass. Final JavaScript whitespace normalization moved the assertion from line 60
to line 61. Locations in the unmodified raw result reflect the tested pre-format
source; no executable behavior changed during formatting.

See the [sanitized two-run result](assets/SURV-000-foundation-diagnostics.json).
Raw command logs remain ignored in `.artifacts/foundation-acceptance/`; foundation
JSON reports are retained in `.artifacts/surveys-infrastructure/foundation/`.
No session files or test traces are committed. The acceptance result proves the
foundation journey and its intentional failure path, not all module journeys,
all personas, the remaining write contracts or the aggregate SURV-100 gate.

## Complete write transport inventory

**000.T1a / 000.S1a accepted.** Source is the commit introducing this section,
based on `b79bc3e`. The broader **000.1 / 000.A1 / 000.T1 / 000.S1** remain open.

The [contract document](../WRITE-CONTRACTS.md) records all current survey write
operation IDs, model sources, authorization, error boundaries, revision/replay
scope and successful persistence effects. Review covered the actual HTTP router,
PostgreSQL survey/export repositories, domain capability policy, neutral package
contracts and the host export-state adapter. It explicitly identifies the generic
Python dictionary port and remaining verification work rather than implying that
all layers already have typed or fully tested contracts.

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" contracts
```

Final run `leonaid-surveys-833458328-97785` exited **0**. The real stack migrated
and passed the existing PostgreSQL/API identity foundation. With its worker
stopped, `tools/surveys/write_contracts_live.py` created/published a survey through
HTTP, started a participation, saved a nonempty answer and checked its exact SQL
value. It then verified an explicit inventory against all **21** registered
POST/PUT/PATCH/DELETE survey routes and validated each nominal fixture using the
route's actual request model.

All **42** negative HTTP calls passed: 21 authenticated extra-field requests
returned 422; 17 syntax-valid member requests without authentication returned 401;
four syntax-valid public requests for a nonexistent survey returned 404. After
each call, full row-content digests for **14** survey/outbox tables matched the
pre-call baseline. This detects updates as well as inserts/deletes and preserves
the nonempty answer fixture. Identity/session activity and security-rate attempt
rows are outside this invariant. No email is sent by these rejected requests.

The subsequent pinned Chromium foundation test passed (1 test, 1.7 seconds),
opening the authenticated member host and public homepage through the real proxy
without mocked routes. This contracts mode uses the original synthetic admin
foundation session; ordinary-member and survey-shell evidence belongs to the
separate foundation diagnostic run above. The harness removed its own containers,
volumes and networks. Explicit unused subnets and no host port publication kept
the run isolated from parallel worktrees.

An earlier run (`leonaid-surveys-833458328-97101`, exit 1) correctly rejected the
test's nominal `example.invalid` email fixture before completing the inventory.
The fixture now uses the reserved example.com domain; the full corrected run is
the acceptance evidence. Ruff and shell syntax checks passed. The
[sanitized result](assets/SURV-000-write-contracts.json) contains operation/model
metadata, observed statuses and table names; it contains no session tokens,
response contents, row digests or temporary resource IDs.

This proves the complete negative transport inventory, not every invalid-field
boundary, valid-resource permission combination, error code/envelope, replay or
concurrency outcome. Those remain part of the parent contract gate alongside
the explicit C-01–C-15 fixture mapping and the existing work-package live proofs.

## Complete runtime dependency disposition

**000.3 / 000.S3 accepted.** Baseline `de0f007` plus this commit's dependency
checker and command wiring. **000.T1 / 000.A1** remain open for their separate
contract/persona requirements. The initial A4 npm admission result above remains
valid and is now complemented by the XLSX closure and distribution checks.

`./leonaid test-surveys-dependencies` exited **0**. Its npm gate verifies the five
exact MIT runtime packages (SurveyJS core/React 3.0.3, React/React DOM 19.2.8,
scheduler 0.27.0), the actual Open Sans OFL-1.1 notice and four negative cases.
The new `tools/surveys/python_dependencies.py` examines installed distribution
metadata and actual license-file bytes for existing openpyxl 3.1.5 and its sole
declared dependency et-xmlfile 2.0.0. Both have MIT metadata, while et-xmlfile also
retains a separate Python-code notice. The full three files were read and their
SHA-256 fingerprints admitted explicitly; a future text change requires review.

Eight independent negative fixtures fail admission: unknown package, unknown
version, commercial metadata, unknown license metadata, added unknown transitive dependency, missing MIT
notice, altered notice, and missing et-xmlfile Python notice. The
[machine result](assets/SURV-000-python-dependencies.json) records exact versions,
requirements, file hashes and the negative count, without local filesystem paths.
The same checker passed with `--network none` inside both actual images
`leonaid-surveys-833458328-1914-api` and `leonaid-surveys-833458328-1914-worker`
from the last editor run. It therefore checks preserved distribution notices in
the deployed image layout as well as the development environment. These were
short-lived audit containers with no application service startup. A separate
import of openpyxl in the actual worker confirmed both optional XML flags,
`LXML` and `DEFUSEDXML`, are false. The gate inventories declared dependencies;
optional parser additions need explicit review rather than inheriting approval
from openpyxl metadata.

`./leonaid test-surveys-package` also exited **0**, project
`surveys-package-833458328-4796`. The independently installed tarball resolves all
six packages (including our UNLICENSED/private package) inside `/consumer`, with
no workspace resolution and no unexpected dependency. The React compatibility
peers remain `^19.2.8`, while the host pins actual React/React DOM to `19.2.8`.
The [packed result](assets/SURV-000-packed-dependencies.json) records installed
versions/licenses, preserved notices and the separate respondent/export bundle
boundaries. Build steps reused content-addressed Docker cache for unchanged
package inputs; the actual browser phases ran afresh.

Four Chromium tests passed: two before the real independent SQLite backend
restart (**6.1s**) and two after it (**1.4s**). They exercise multipage saving,
translated host editor controls, restored answers without an extra save and
restored editor drafts. The harness removed its named container, volume, network
and temporary image, with no host port publication.

The final selection requires no third-party drag/drop or browser-chart runtime:
both are independently implemented in the neutral package. XLSX/chart generation
uses the already pinned openpyxl pipeline and CSV uses Python's standard library;
PDF uses the existing pinned Typst integration. No Survey Creator, Dashboard or
SurveyJS PDF Generator is selected. [DEPENDENCIES.md](../DEPENDENCIES.md) now
records this actual disposition instead of its obsolete no-lockfile planning
state. The checker scope does not claim a full license audit of all existing
LeonAid or base-image dependencies. Future additions and final SURV-100 artifact
review remain required. Own license remains **UNDEFINED**; no manifest/license
choice changed. Ruff, shell syntax and diff whitespace checks passed.

## Persona and fixture foundation

**000.4 / 000.S2 accepted.** Runtime baseline `fce4fe4`; this change adds
review documentation and evidence only. The broader **000.A1 / 000.T1** contract
and capability traceability gate remains open.

The following command exited **0** in fresh project
`leonaid-surveys-833458328-6734`:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" permissions
```

The actual API/PostgreSQL foundation migrated empty volumes and verified stored
values. The permissions fixture then created 14 personas across four resource
contexts. Its independently specified expectations verified **56 persona/resource
pairs**, **127 allowed reads**, **723 denied reads**, and **891 denied writes**.
Denied operations preserved SQL fingerprints; list totals, search and pagination
remained scoped. The [sanitized result](assets/SURV-000-personas.json) records
these counts and all 28 desktop/mobile persona cases (112 browser resource pairs),
without tokens, response contents or temporary resource IDs.

The full Chromium permissions suite completed successfully, including foundation,
publisher-only review, invitation controls, invitation-only users, role lifecycle
and deletion scenarios. The command verified removal of its owned containers,
volumes and networks; it published no host ports. No unrelated worktree stack was
removed. Existing artifact files for other harness modes are not claimed as
results of this run.

[ROLES-AND-DATA.md](../ROLES-AND-DATA.md) records the source-reviewed capability
mapping, durable entities, constraints and migration sequence. The deterministic
three-page Krapfentaxi/golf JSON definitions and real-API publication seed are
complemented by the [template/editor regression](SURV-040.md#template-creation-and-editor-regression).
Fresh UUIDs and temporary credentials isolate runs while fixture relationships
and behavioral expectations remain deterministic. The existing
[deliberate-failure proof](#foundation-browser-failure-diagnostics) supplies the
separate sanitized diagnostics/nonzero-exit acceptance required by 000.A3.

This closes the fixture/infrastructure task, not the final SURV-100 whole-product
journeys or all C-01–C-15 contract outcomes. Own license remains **UNDEFINED**.
