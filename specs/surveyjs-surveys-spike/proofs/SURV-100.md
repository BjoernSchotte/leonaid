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
