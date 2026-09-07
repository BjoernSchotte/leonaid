# SURV-100 — Acceptance evidence in progress

Overall status: **open**. This file records scoped checks; it does not accept the
aggregate lane, complete sample journeys, recovery gates or remaining regressions.

## React peer policy and packed consumer

Source: the commit introducing this section, based on `84cfab6`.

| Task | Implementation and assertions | Result |
| --- | --- | --- |
| 100.3a | `tools/pins/check.py` permits only `react` and `react-dom` at `^19.2.8`, only in `peerDependencies` of `packages/surveys/package.json` with the expected package name. Direct LeonAid hosts must declare both runtimes at exactly `19.2.8`. | Accepted |
| 100.3a policy negatives | `tools/pins/peer_policy_test.py` rejects broader/different ranges, unrelated dependencies, other sections/paths/names, and missing/ranged/unproven host runtimes. The existing image, Python and frontend drift fixtures remain active in `tools/pins/test.sh`. | Six peer-policy tests and four existing negative cases pass |
| 100.3a installation | Frozen workspace installation keeps the lock unchanged. The packed consumer installs with its separate frozen lock, asserts peer declarations and actual exact runtime versions, and resolves no LeonAid workspace package. | Pass |
| 100.3a browser integration | `tests/e2e/surveys-package.spec.mjs`: multipage response saved through the real SQLite adapter; editor translation preserves author content/history; backend restart restores both respondent data and editor draft without an extra respondent save. | Four Chromium tests pass |

The package's compatibility declaration stays distinct from tested runtime
versions. This is evidence for React/React DOM **19.2.8**, not proof of future
versions in the peer range. SurveyJS core/React renderer remain **3.0.3**. No
dependency version, lockfile or own license decision changed. The package remains
private/`UNLICENSED`; the intended own license remains **UNDEFINED**.

Commands (repository root; all exit zero):

```sh
# Pinned UV image from infra/locks/images.env, with network disabled:
uv run --frozen --no-sync sh tools/pins/test.sh /workspace
uv run --frozen --no-sync ruff check tools/pins/check.py tools/pins/peer_policy_test.py
uv run --frozen --no-sync mypy tools/pins/check.py tools/pins/peer_policy_test.py
# Pinned Bun 1.2.19 image, with network disabled:
bun install --frozen-lockfile --ignore-scripts
# Host orchestration; builds and runs pinned containers:
rtk proxy sh tools/surveys/package.sh "$PWD"
```

The UV/Bun commands run with the repository mounted at `/workspace`, working
directory `/workspace`, and `PYTHONPATH=/workspace` for Python. The full pin
checker accepts 23 images and 89 Python packages. Bun reports 433 installations
across 542 packages, with no changes. Ruff and strict MyPy accept both Python
files. The packed consumer inventory is retained in
[SURV-100-package.json](assets/SURV-100-package.json).

The consumer harness allocates a unique worktree/PID project, selects an unused
subnet, publishes no host ports and removes its own container, data volume,
network and image. It uses an empty SQLite volume and restarts the actual backend
between browser groups. The final run used `surveys-package-833458328-74769`;
the two Chromium groups passed in 7.3 seconds and 2.1 seconds, and teardown
completed with exit zero. Build layers may be cached; this is not a claim of an
uncached dependency download or the full clean-stack aggregate gate.

Remaining: 100.1–100.4, 100.T1–100.T2 and 100.A1–100.A5 remain open except for the
specific 100.3a contribution above. Complete affected regression suites, both
full desktop/mobile sample journeys, predecessor recovery acceptance and the
capability/outcome report before declaring SURV-100 complete.

## Isolated pilot operator regression

**100.3b / 100.S2a are accepted as an additional affected-regression contribution
to 100.A3.** Overall 100.3 and 100.A3 remain open. Source: the commit introducing
this section, based on `90cbbdb`.

The previous pilot harness used shared source/build/backup/restore names, fixed
ports and unconditional pre-start cleanup. `tools/pilot_deployment/test.sh` now:

- derives unique project and image names from worktree checksum and process ID;
- rejects existing matching containers, volumes, networks, backup names and tags
  before taking ownership; removes only resources of this run;
- selects four available loopback ports, with optional explicit port inputs;
  another process winning a port race causes startup failure, not cleanup of that
  process;
- selects unused explicit source subnets and selects target subnets after the
  source networks exist, using per-run ignored Compose overlays;
- keeps the source running while the separate target is restored;
- validates the runtime Compose JSON on the host and streams that exact snapshot
  into the release-manifest container, avoiding a second read of a refreshed file
  in an already shared directory.

The `leonaid` test-only overlay/decision/Doctor guards now also accept suffixed
`leonaid-production-test-*` and `leonaid-staging-test-*` projects. Existing
production/staging names do not gain access to these test hooks. The harness
treats `LEONAID_PILOT_DEPLOYMENT_PROJECT` as a prefix; runtime/build projects are
always generated together rather than accepting independent shared names.

| Task | Live evidence | Result |
| --- | --- | --- |
| 100.3b isolation and boot | All 13 services become healthy, including the actual SurveyJS validator. Source/target run concurrently with separately selected subnets and loopback ports. Production Compose contract and seven negative mutations pass. | Pass |
| 100.3b deploy/release | Six unsafe Doctor input mutations, real TLS/readiness probes, manifest drift rejection, staging-promotion requirement, maintenance, migrations and four release-ledger events are checked by the full harness. Deployment uses the verified immutable image inventory. | Pass |
| 100.3b backup/restore | Actual encrypted remote-S3-compatible Restic backup, read-data integrity check, rejected bad password/restore confirmation, real `pilot-restore`, checkpoint gate before startup and healthy no-build target. Core DB, Twenty DB, RustFS and Twenty storage probe contents match. | Pass |
| 100.3b teardown | Post-run Docker queries find no containers, volumes or networks for any of the four owned projects, and all five build tags are absent. | Pass |

Exact command from the checkout root:

```sh
rtk proxy sh tools/pilot_deployment/test.sh "$PWD"
```

The successful run is `833458328-77303`, exit **0**, using the pinned images in
`infra/locks/images.env` and five images built from this checkout. The full local
log is ignored at `.artifacts/pilot-isolated-live.log`. Commit only the sanitized
[result](assets/SURV-100-pilot-regression.json), not environment files, backup
contents or deployment manifests containing operational configuration.

Two earlier runs (`833458328-75825`, `833458328-76433`) exited 1: the manifest
container read truncated or empty runtime Compose JSON from the shared directory.
Both were cleaned up. A fresh filename alone did not resolve the failure. In the
successful run the host parsed all 22,626 bytes, and stdin delivery allowed the
actual manifest parser and complete downstream operator flow to pass. The exact
filesystem/cache mechanism was not independently diagnosed.

This is an operator integration test, not browser E2E. Its survey checkpoint has
**zero erasure records**, and the source remains available. The subsequent
[090.2g proof](SURV-090.md#pilot-restore-with-post-backup-survey-erasure) covers
nonempty deletion recovery and five rejected inputs through the wrapper after
source-project removal. Latest-checkpoint provenance across unexpected host
loss, interrupted reapplication and preceding backup compatibility remain open
under 090.2/090.A3. The affected identity, policy and public/browser regressions
and the full spike acceptance also remain open.


## Isolated identity policy and public regressions

**100.3c / 100.S2b accepted.** Source: this increment based
on `b3f8dcc`. The four named regression entry points previously defaulted to
shared project names, published fixed host ports and unconditional initial
`compose down --volumes`. Their test scripts now:

- Append the worktree checksum and process ID to the default or operator-supplied
  project prefix. An override is a prefix, not an instruction to reuse/clear an
  existing project.
- Check container, volume and network inventories before taking ownership.
  Existing resources or a failed inventory command abort before mutation.
- Select currently unused explicit subnets using the existing test allocator and
  merge its no-host-port overlay into every Compose invocation. API/DB and browser
  checks use internal service DNS and the project's own edge network.
- Diagnose and remove only a project owned by the current run. Teardown failure or
  remaining owned containers, volumes or networks makes the command fail.

The identity contract contained an obsolete expectation that the acquirer had
no web navigation. The survey module intentionally grants authenticated members
its own entry without granting other backoffice roles, already covered by the
identity domain contract. The live assertion now requires exactly `{surveys}`.
The existing browser redirection test still proves that `/admin/` and
`/admin/members` redirect the acquirer to the PWA; it additionally opens
`/admin/surveys` and verifies the survey heading/navigation while overview,
members, system and invoice navigation remain absent. No runtime permission or
navigation implementation changed in this increment.

`tools/testing/regression_isolation_test.py` executes the actual four shell
scripts with a synthetic Docker executable. For each suite, existing containers,
volumes, networks and failed inventory reads are tested: **16 subcases in one
unittest test pass**. Only the expected read-only inventory commands may run;
no Compose/down/remove call is permitted. This is a negative guard test, not a
substitute for the actual Docker/browser regressions below. The existing
`tests/unit/test_identity_domain.py` also passes **28 tests**.

Commands (repository root):

```sh
rtk proxy ./leonaid test-identity
rtk proxy ./leonaid test-policy
rtk proxy ./leonaid test-public-actions
rtk proxy ./leonaid test-public-orders
rtk proxy python3 tools/testing/regression_isolation_test.py
```

The four live commands run sequentially, each from its own empty volumes. Their
complete original contract/browser coverage is retained, with the reviewed survey
navigation expectation above. Raw logs remain in the ignored
`.artifacts/survey-regressions/attempt-2/` directory. Identity screenshots remain
in the existing private evidence directory; no credentials, token files, database
contents or unrestricted logs are part of committed evidence.

The initial identity run `leonaid-poc040-test-833458328-37504` exited 1 on the stale
navigation assertion before browser execution; it was cleaned before the corrected
run. No executing test or runtime file was edited. Build layers may be cached;
this is a fresh-volume proof, not a claim of an uncached dependency download.

This is a contribution to **100.A3**. The broader `./leonaid test-integration`
currently invokes 42 suites and remains a separate requirement; the full survey
aggregate, complete desktop/mobile sample journeys and recovery continuity remain
open. Do not accept **100.3**, **100.A3** or the whole spike from these four commands
alone. Own license remains **UNDEFINED**; no dependency/license decision changed.


| Complete command | Final project suffix | Observed result |
| --- | --- | --- |
| `./leonaid test-identity` | `833458328-39066` | Exit 0, 181.7 s; live role/status/revision/idempotency/concurrency/session-revocation contracts and 10 Chromium browser tests (21.1 s). |
| `./leonaid test-policy` | `833458328-39606` | Exit 0, 132.8 s; actual PostgreSQL/Twenty lists, search, counts, export, activity, document authorization and immediate revocation. |
| `./leonaid test-public-actions` | `833458328-40358` | Exit 0, 107.2 s; Core/Astro contract, four browser runs (7.2 s) and one accessibility/performance audit test (2.2 s). |
| `./leonaid test-public-orders` | `833458328-40663` | Exit 0, 151.2 s; legal basis, organization/person identity, server prices, idempotency, inactive/archive rejection, spam/rate controls and activity events; one Chromium test (13.5 s) exercises three visible order paths and persisted results. |

Each command's cleanup verifies its own containers, volumes and networks are gone.
A separate post-run Docker query also confirmed cleanup of all four successful
projects and the initial failed identity project. Live Docker inspection observed
zero host-port bindings on 13 running identity containers and 10 running public-action
containers; all four scripts use the same explicit no-host-port override. Public
browser coverage is the existing configured Chromium desktop/mobile, Firefox mobile
and WebKit mobile matrix. Browser audit results are automated observations, not
manual visual review or a general accessibility certification.

[Sanitized results](assets/SURV-100-existing-regressions.json) record commands,
terminal codes, elapsed times, project names, browser counts and the exact port
observations. Shell syntax, Ruff for the changed Python files, Prettier for the
changed browser test, local Markdown links and staged whitespace/private-value
checks pass. No application runtime behavior changed in this increment.


## Complete desktop and mobile survey journeys

Accepted: **100.T2 / 100.A2 / 100.S4**; implementation delivery **100.2** is checked.
The separate **100.2** task-acceptance box stays open for **100.A4**'s complete
capability/task reconciliation. This proof does not close aggregate CI, the twice-run
full suite, remaining existing regressions, disaster recovery or the final report.

Tested revision: `ebcadc7` plus the three source files committed with this proof.
Their exact SHA-256 values and the content-free results are recorded in
[the journey artifact](assets/SURV-100-journeys.json).

| Task | Deliverable / assertions | Result |
|---|---|---|
| 100.2 | Four complete sample journeys in `tests/e2e/surveys-journey.spec.mjs`; real storage/export inspection in `tools/surveys/journey_verify.py` | Delivered; A2 accepted, A4 remains open |
| 100.T2 | Both templates at 1440 × 960 and 390 × 960, through actual member/public UI, API and worker | Passed |
| 100.A2 / 100.S4 | Persisted partial answers, fresh-context resume, immutable version isolation, outsider denial, analysis, four export products and permanent erasure | Passed |

Command from the worktree root:

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" journeys
```

Final project: `leonaid-surveys-833458328-49837`. Exit **0**. Playwright **1.54.1**,
pinned Chromium **139.0.7258.5**, five tests passed (four journeys and existing
identity/public-host foundation), reported browser duration **1.2 minutes**.
Pinned runtime/service images come from `infra/locks/images.env` and Compose.
Actual FastAPI, PostgreSQL, SurveyJS validator, worker, Mailpit, RustFS and Typst
were used. No survey persistence, authorization or export endpoint was mocked.

Each case creates its template in the member UI, edits the first question,
sets a two-second inactivity override and publishes version 1. Krapfentaxi uses
a public link; Golf uses an invitation sent through the real worker and read
from Mailpit. An ordinary member without survey access sees the denial UI and
receives 404 for administrative reads, analysis and each export download.

The respondent answers page 1 and part of page 2; the UI confirms saving and
the API returns the exact comment and version. The whole respondent context is
closed. While it is absent, the author edits and publishes version 2. A fresh
context with the original protected browser session reads status `partial` and
restores the exact answers, original version/title and unchanged revision.
A second participant receives version 2 (a second actual invitation for Golf).
The original participant finishes page 3 and completes against version 1.

The author selects version 1 and creates its analysis in the UI. Its count is
exactly one, excluding the version-2 participation. Visible question titles and
all five per-question counts match the returned immutable snapshot; the author
opens the table alternative. All four products are requested and downloaded
through the UI, and every export job is bound to that same snapshot.

The independent verifier parses the **16 actual browser downloads**. Raw CSV
and XLSX agree for every XLSX column, contain exactly the completed original
participation and retain its Unicode comment. Analysis XLSX metadata and all
metrics match the snapshot, with native charts present. PDF extraction verifies
the snapshot identity and every question's denominator counts. Both aggregate
formats exclude the raw comment. This is content/structure verification, not a
new manual PDF or chart layout review; earlier SURV-080 render evidence remains
separate.

Each author then ends, archives, trashes and permanently deletes the survey
through its confirmation UI and waits for completed erasure. Old participation
and export URLs return 404. Independent SQL inspection finds no remaining survey,
draft, version, participation, operation, invitation, snapshot, export-job or grant
content, and a completed deletion ledger. Paginated S3 version listing finds
neither object versions nor delete markers under the survey prefix.

Four preceding runs exited 1 while refining test interactions: `45140` (exact
native select label and dropdown input target), `46088` (popup auto-scroll),
`47515` (layout/hit-test diagnosis), `48540` (collapsed analysis table and mobile
popup settling). The final Golf selection waits until the option is hit-testable
and uses a normal pointer click at that visible point. Playwright's locator
scrolling dismissed the fixed popup; no forced click, DOM answer mutation or
product CSS workaround was used.

All five projects were independently checked after termination: **zero owned
containers, volumes and networks remained**. Every run allocated seven unused
explicit subnets and disabled host-port publication; parallel projects were
untouched. Raw traces, emails, credentials, answers and downloads remain transient
or ignored locally; the committed artifact contains only synthetic test labels,
counts, booleans, source hashes and run metadata.

Supporting checks: Ruff on `journey_verify.py`, Prettier on the browser test,
shell syntax validation and `git diff --check` passed. No application behavior
was changed by this increment.


## CI transport boundary and complete runtime SBOM inventory

Verified on 2026-09-07 across baselines `f9ed1f1` and `3839c0b`, plus the exact source hashes in
[the sanitized record](assets/SURV-100-ci-boundaries.json). This is a scoped
regression repair, not acceptance of the entire SURV-100 gate or remote CI.

The generated-client boundary already allowed the independent demo respondent's
own backend routes but incorrectly rejected its editor and export adapters.
The checker now allows only seven reviewed route forms in three exact demo files.
It still rejects LeonAid `/api/v1` calls, unreviewed files/routes, unencoded export
IDs and direct generated-client imports. The current full frontend scan passed;
all **16 boundary tests** passed in the pinned Python container. No package or
production frontend code changed for this correction.

`rtk proxy sh tools/surveys/package.sh "$PWD"` exited **0**. The packed artifact
was installed outside workspace resolution with frozen dependency versions;
package/bundle/license inspection passed. Four Chromium cases passed (**8.3s**
before restart and **2.3s** after restart): multipage persistence, actual CSV
export after lost acknowledgement, translated editor with retained undo/history,
and restoration of respondent/editor state through the real SQLite backend.
Project `surveys-package-833458328-68312` used an unused internal subnet and no
host ports. Cleanup and a separate container/volume/network absence check passed.

The SBOM shell loop already enumerated Prometheus and Alertmanager but failed
because their pinned image variables were not assigned. Both assignments are
now explicit, and verification requires both artifacts rather than accepting
the older incomplete set. Command:
`rtk proxy sh tools/sbom/generate.sh "$PWD" "$PWD/.artifacts/sbom-surveys-ci"`.
Exit **0**: Python, frontend and **15 runtime images**, totaling **17 nonempty
CycloneDX documents**. Each image is scanned from its pinned registry reference.
Two negative checks omitted each new artifact separately from the actual results;
both returned exit **1** and identified the missing document. Artifact hashes
and component counts are recorded without copying raw inventories into the proof.

The two checkpoint unit files flagged by CI were formatted without behavior
changes. The combined boundary/archive/publisher suite passed **35 tests** in
the pinned UV image with `PYTHONPATH=/workspace/src:/workspace`. An earlier manual
invocation omitted that variable: four subprocess-based archive checks failed
with `ModuleNotFoundError`; the corrected invocation exercised those same cases
successfully. No failed run is counted as passing evidence.

Full existing integration regression, aggregate repetition, remote workflow
results and the remaining recovery/capability audit stay open.


## Isolated Compose regression

**100.3d / 100.S2c** accepted against `b18b534` plus the exact source hashes in
[the sanitized result](assets/SURV-100-compose-regression.json).
The existing Compose test expected the pre-survey service inventory and selected
a fixed project with a destructive initial reset. It now includes the actual
validator service and selects a checkout/PID-specific project, seven unused
explicit subnets and two distinct free loopback ports. The optional configured
ports are checked by binding actual sockets before Docker starts. Only the proxy
may publish ports, as verified from every running container's real bindings.
There is no initial `down`; unreadable inventories or existing project resources
stop execution before any Docker mutation. Cleanup failure/remaining resources
produce failure rather than a false success.

Command: `rtk proxy sh tools/compose/test.sh "$PWD"`, executed by a private-log
wrapper. Exit **0**, project `leonaid-poc010-test-833458328-72306`. The complete
original assertion sequence passed: all thirteen default services and health,
HTTP/TLS readiness and host routes, golden PostgreSQL/RustFS writes, full restart,
exact persisted golden data and unchanged Twenty schema count, optional Mailpit,
Listmonk and OpenTelemetry readiness, and the real proxy mail/mailing routes.
Successful teardown was followed by a separate empty Docker label inventory for
containers, volumes and networks. Other worktree resources were not selected.

`rtk proxy python3 tools/testing/regression_isolation_test.py` exited **0** with
**20 collision/inventory cases** across Compose and the four previously isolated
regressions. These negative process-boundary fixtures assert that no compose,
remove or down command occurs; real service behavior is proven by the live run
above, not by those fixtures. This is operator/HTTP integration evidence, not
browser E2E. The other existing regression suites and full **100.A3** remain open.


## Aggregate command and CI lane under verification

The new `./leonaid test-surveys` command reads one manifest of 37 checks in eight
ordered groups. Each selected check runs sequentially in a checkout, with an
exclusive aggregate lock, owner-only raw logs and separate structured result
metadata. Seven real process-control tests pass, covering nonzero/missing child
commands, repeated execution, log redaction, competing locks, forwarded termination
and cleanup, and manifest coverage/recursion rejection. The integration, exports
and E2E aliases select documented groups; [TEST-GATE.md](../TEST-GATE.md) records
scope and operator instructions.

The workflow uses that same group inventory on separate ephemeral runners and
executes each group twice. It uploads only structured result JSON, never raw
service output, downloads or traces. Publishing the workflow to the draft PR
starts actual remote verification; it is not acceptance of **100.1 / 100.A1**.
The local full `--repeat 2` run started at `b18b534` is also still in progress.
The earlier deliberately interrupted run remains unaccepted. Final results and
their tested-source scope must be recorded before checking the aggregate criteria.


The first actual Survey acceptance run, `34154722678` at `4eaab14`, failed
before any survey test: the existing pin scanner interpreted the workflow's
inline Python `from pathlib import Path` as a Docker `FROM pathlib` instruction.
The workflow now uses `import pathlib`; the full current pin check and workflow
format check pass. No image selection or pin rule was weakened. The initial
missing-artifact errors are consequences of bootstrap failing before the gate
created a result. That remote run is not accepted; a new run is required.


The second remote run, `34154993662` at `cdf6976`, passed bootstrap but failed
inside every group's actual test command. Foundation reached its real-browser
diagnostics check; package failed its packed-consumer check. The structured exit
records alone did not expose the underlying cause. Four passing bounded-diagnostic
tests and a local extraction against actual logs now verify fixed category/public
location output without raw messages or private values. The workflow publishes
that separate metadata on subsequent runs. This improves failure investigation;
it does not convert either failed run or the local in-progress aggregate to an
accepted gate. The new metadata must be inspected from the next actual run.


### Linux CI proof ownership correction (verification pending)

Run `34156132726` at `478b60f` completed with all eight groups failing;
every group exposed the bounded `permission-denied` marker. The infrastructure
harness creates `session.env` as container root with mode 0600, then the host
Docker client reads it for `--env-file`. On a Linux runner the unprivileged
controller cannot read that bind-mounted file. Root-created result directories
also cross this ownership boundary during host cleanup. Docker Desktop file
sharing did not expose this Linux ownership mismatch in the local successful runs.

A real pinned Linux Python container reproduced a UID-1001 read failure for a
root-owned 0600 synthetic proof, while its owning controller read the same file
without changing permissions. The first probe lacked SETUID/SETGID and failed
before the read; the corrected probe enabled only those two capabilities and
passed. The CI aggregate and bounded collector now run with the proof owner's
UID on the disposable runner. Only the exact checkout is added to root Git's
safe-directory list, so commit identity and public-file enumeration still work.
Application service identities and proof permissions are unchanged. This is a
source-grounded correction for a reproduced ownership boundary, not a claim that
it explains every remote failure. A new actual CI run must confirm the result;
**100.1 / 100.A1 remain open**.


## Reserved networks and seven backend regressions

The seven existing suites now use checkout/PID-specific projects, explicit
subnets, no published ports, inventory checks before mutation and cleanup that
fails if owned resources remain. The original assertions are preserved.
Merely selecting currently free subnets proved insufficient: the first isolated
Twenty run failed when its deferred telemetry network collided with a concurrent
run. Its owned resources were removed and independently verified absent.

The new reservation helper creates every configured owned network before service
startup, preserving Compose labels and internal-network flags. Docker itself
arbitrates each allocation; occupied subnets are retried with other candidates.
It validates the entire configuration before creating anything and rejects
foreign names. Schema's intentional database reset re-reserves its owned networks.
A real Docker proof occupied the proposed subnet first, verified two collision
recoveries, unchanged blocker identity/subnet, internal flags, distinct allocated
subnets and exact owned cleanup. A foreign-name configuration was rejected
without creation. All 48 collision/unreadable-inventory guard cases across the
twelve adapted harnesses pass. Those process-boundary fixtures do not substitute
for the real Docker/service evidence.

All seven full suites then exited **0**, sequentially, with seven networks
reserved before service startup: core, schema, outbox, OpenAPI, Twenty metadata,
CRM gateway and CRM import. The gateway stopped Twenty for real, verified safe
errors, restarted it and checked persisted data. Metadata provisioning was
idempotent and detected deliberate drift; the golden XLSX import exercised dry
run, controlled create/update, repeat execution and idempotency. A separate Docker
inventory after completion verified zero owned containers, volumes and networks
for every project. [Result durations, project IDs and tested source hashes](assets/SURV-100-backend-regressions.json) record the evidence.

This accepts **100.3e / 100.S2d**, seven additional legacy regression suites.
It does not accept the remaining legacy suites, full aggregate, actual CI lane
or broader **100.A3**. No browser coverage is inferred from these CLI/API tests.


Run `34157145093` at `9b50c67` confirmed that both actual packed-consumer
iterations pass with the corrected Linux controller identity. The package job
then failed only in artifact upload: the structured results were below the
owner-only gate directory. The workflow now copies only top-level result JSON
and the fixed bounded-diagnostic JSON into a separate upload directory and
makes only those reports readable. Private logs, traces, session files and their
directory permissions remain unchanged. A fully successful remote run, including
artifact delivery, is still required before aggregate acceptance.

A real pinned Linux container verified the report-copy boundary: UID 1001 read
exactly the two copied JSON reports while the root-only raw log remained
inaccessible. The first invocation had a mistyped image digest and did not start
a container; the successful invocation read the pin directly from images.env.
Workflow formatting and the full 23-image/89-Python-package pin check pass.


Run `34157527487` at `d3a86f7` exposed another upload boundary: its runner
could not create the upload subdirectory under root-owned `.artifacts`. The
workflow now stages those same two allowed report classes under the runner's
own temporary directory. The Linux copy/read proof above remains applicable;
source logs stay behind the owner-only gate directory. Foundation's migration
leaf also failed after five passing leaves, independently of upload. Its raw
child log was not exposed, so the cause is still unconfirmed. Fixed PostgreSQL
error markers were added to the bounded classifier for the next real run. All
four diagnostic privacy tests and workflow formatting checks pass.


### Confirmed structured CI results after upload correction

Run `34157914748` at PR head `c8035cc` (GitHub merge checkout
`f4116a335d86e1f004adfb2323a8135bba2892b6`) published readable structured
reports. Package passed both packed-consumer iterations (50.772 s and 23.080 s).
Foundation passed all seven leaves in both iterations, including both migration
runs and deliberate failure-diagnostic acceptance. Their bounded reports were
downloaded and inspected; private logs remained excluded.

The E2E group failed its first journey iteration at the Golf dropdown option
hit-test (`surveys-journey.spec.mjs:316`). No cause is yet confirmed, and the
second iteration did not run. Other groups and the local aggregate are still
running. Neither this partial CI result nor previous local journeys accepts
the full current remote gate.

An independent real PostgreSQL initialization probe also demonstrated that the
existing migration readiness check can accept the temporary Unix-socket server
while TCP is still unavailable. Waiting for 127.0.0.1 TCP readiness allowed real
SQL create/write after final startup. The probe used a temporary init hook, no
network/host ports and removed its owned container. A TCP-readiness patch is
prepared but not yet applied, to preserve the executing aggregate's sources.
This observed race is not asserted as the unobserved cause of the earlier CI
migration failure.


## Six isolated browser regressions

The complete existing invitation, session, matching, assignment, activity and
action scripts now reserve all owned networks before startup, use checkout/PID
projects, reset host-port publications and refuse occupied/unreadable inventories
before mutation. Their original API, SQL, SMTP, Twenty and Playwright assertions
are unchanged. Each command exited **0** and its required screenshot checks
passed. A separate Docker inventory verified no owned containers, volumes or
networks for all six projects after completion.

| Suite | Browser result | Covered existing behavior |
|---|---|---|
| invitations | 6 passed, 36.9 s | Action-scoped invitation rights, admin action choices, lifecycle/resend/address correction, mobile code entry, confirmed email change; real SMTP/outbox contract |
| sessions | 2 passed, 10.7 s | Login, fresh-login and session lifetime/revocation contracts, real browser login/finance routing |
| matching | 1 passed, 22.9 s | Real Core/Twenty matching and mobile ambiguity/warning/no-match/create outcomes |
| assignments | 1 passed, 24.8 s | Real concurrency/history/shared-assignment contract and mobile matching warning/success |
| activities | 1 passed, 10.1 s | Recorded activity, follow-up/history and browser persistence |
| actions | 1 passed, 11.5 s | Neutral action contract and full browser creation |

[Run durations, project identities and source hashes](assets/SURV-100-browser-regressions.json)
record the tested harnesses. The previously verified reservation helper is unchanged.
The expanded guard suite covers 72 occupied-resource/unreadable-inventory cases
across the eighteen adapted legacy harnesses; those process-boundary fixtures
complement the real service/browser tests above. No new visual/accessibility audit
is inferred from screenshot existence or passing browser assertions.

This accepts **100.3f / 100.S2e**. Eighteen of the 42 legacy regression scripts
have now been isolated and executed; the remaining 24, the full Survey aggregate,
current whole-journey CI failure and recovery requirements remain open.


## Exact public CI report upload boundary

The Security job for revision `02a4bff` correctly rejected the new workflow upload
location because the repository's allowlist had not been updated with the report
staging change. The upload remains limited to
`${{ runner.temp }}/surveys-ci-results/*.json`; no broader temporary-directory
prefix is allowed. Raw gate logs stay outside this public staging directory.

`tools/pilot/boundary.py` now allows that exact expression.
`PYTHONPATH=. python3 tools/pilot/test.py` passes against the real Git index/history,
private file permission probes and workflow inventory. Six additional negative
cases reject recursive JSON globs, all-file globs, log globs, the whole runner
temporary directory and raw survey gate directories/logs. Existing private pilot
and unknown-upload-action rejection cases remain unchanged. All four bounded
survey diagnostic tests pass, as do scoped Ruff formatting and lint checks.
This corrects the observed CI failure; a complete new Security/CI run is still
required and is not inferred from these targeted checks.
