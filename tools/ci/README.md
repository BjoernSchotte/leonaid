# CI runtime

## Tiers

There is no merge queue: GitHub offers none for a repository owned by a
personal account. `main` is proven by scheduled runs instead of a run per
push (decision 2026-11-07). Browser E2E follows Björn's policy of the same
day: pull requests run only the E2E leaves their change reaches, the
3-hourly main run none (smoke only), the nightly run all of them.

| Event | What runs |
|---|---|
| `pull_request` into `main` | Always: Lint, types and unit; Build; Security; Documentation. Stack suites (Integration shards incl. Contract, EmDash proofs, Golden Journey, Surveys, API contract, pins) when their inputs changed; shared infrastructure and unmapped paths select all of them. E2E leaves only when mapped (module paths and specs, or the import graph for `src/leonaid/**`), plus the short `smoke` leg for every shared or unmapped change. |
| `pull_request` with the `full-e2e` label | As above plus every E2E leaf. The label is read from the event, so it takes effect at the next push (or start `ci.yml` by `workflow_dispatch` on the branch for a complete run now). A `labeled` trigger is deliberately absent: a run for an unrelated label would replace the PR's gate result. |
| draft `pull_request` | No suite. The gates (and `Bilingual site artifact`) **fail** with "draft: no CI ran", so a stale result can never pass between `ready_for_review` and the new run's gate. `ready_for_review` starts the normal run; `converted_to_draft` cancels a running one through the shared concurrency group. Agents open PRs as drafts and mark them ready when done. Expect red checks (and GitHub's failure notifications) on every draft push; `gh pr checks` reports a draft as failed; `flake_summary.py` ignores such runs. |
| `pull_request` `edited` | A base change (a stacked PR retargeted to `main`) runs the normal selection against the new base. A title or body edit runs no suite, in its own concurrency group (it never cancels the real run); its gate mirrors this commit's newest real gate check run (by id, so a queued newer run wins over an older green one) and waits up to 100 minutes while it is queued or running; after that it fails with "re-run this gate after the real run finishes" (`gate.py`). `docs.yml` simply rebuilds. |
| stacked `pull_request` (base is another branch) | Lint, types and unit; Documentation; only the suites that module-local paths select. Shared infrastructure, unmapped paths and the API/pins path filters select nothing; Security and Build are skipped (`heavy=false`). Defence in depth: such a gate fails when the PR's current base, read from the API, is no longer the stack base. |
| `schedule` every 3 hours on `main` (`37 */3 * * *`) | Every suite except the E2E leaves, plus the smoke leg. |
| nightly `schedule` (`7 3 * * *`), `workflow_dispatch` | Everything, including every E2E leaf. |

`nightly-watchdog.yml` runs after every completed scheduled run
(`workflow_run`) and daily. It opens one issue per watched entry when its
latest scheduled run on `main` is red or overdue, and closes it on green.
`ci.yml` and `surveys.yml` are each watched twice: every scheduled run (8
hours) and the nightly run alone (30 hours, matched by its run name: `LeonAid
CI nightly (every E2E leaf)`, `Survey acceptance nightly (recovery and
backup)`). A green 3-hourly run cannot hide a red nightly one; the contract
requires this for every workflow with more than one schedule. Scheduled runs
on `main` are never cancelled, and each cron has its own concurrency group,
so a still-queued 3-hourly run cannot cancel a pending nightly run.

The **smoke leg** (`tools/ci/e2e.sh smoke`, always alone in its leg) runs
three existing tests on the prepared fixture: the real login flow
(`sessions.spec.mjs` "login, normal work, fresh login, admin action and
logout"), one list view (`modules-tasks.spec.mjs` "admin: S1 compact rows,
status undo and concurrent conflict") and one public order
(`public-orders.spec.mjs` "new company, existing company and private person
order in the guided form", with its Core/Twenty verification). Each leaf filters its own specs with `--grep` when
`LEONAID_E2E_SMOKE=1`.

The **import graph** (`e2e_owners`) parses `src/leonaid/**` with `ast`. A
changed module selects the leaves that own it or any module importing it,
directly or transitively, by module stem (`E2E_OWNERS`: `invoices` →
`invoices`, `invoice-flows`; `sessions` → `membership`; ...). A shared
domain module therefore fans out to most leaves. LeonAid wires adapters and
entry points by dependency injection, so the graph cannot reach them;
`MODULE_OWNERS` maps them by module prefix (`adapters/mail` → membership,
invoice flows, public orders; `adapters/twenty` → matching, acquisition;
`adapters/typst` → invoices; the outbox and worker handlers → every
messaging leaf). The HTTP surface (`entrypoints/fastapi/routes.py`, schemas,
security), the wiring, configuration and the platform select **every** leaf.
A module with no owner selects every leaf too, unless it is in the reviewed
`E2E_NEUTRAL` list (monitoring, metrics, operator CLIs, documents; each with
a reason). `select_suites_test.py` enumerates every `src/leonaid` module, so
a new one cannot fall to the smoke leg silently.

A stack (for example `md/stage2a` → `md/stage2b` → …) is tested in full only
on its way to `main`: its pull request into `main` runs the normal selection
on the combined diff, and the scheduled runs on `main` cover the rest.
Intermediate pushes of the stack only pay for what their own module paths
need. The gate stays fail-closed: a missing `heavy` output counts as selected.

`tools/ci/select_suites.py` decides the pull-request selection; the reusable
`.github/workflows/select-suites.yml` runs it once per workflow and exposes the
result as job outputs. Matrices read their legs from it, so
`INTEGRATION_SHARDS`, `E2E_SHARDS` and `EMDASH_GROUPS` in that file are the
single source of shard names. A new shard goes there, into
`INTEGRATION_SECONDS` / `E2E_SECONDS` (its measured test-step seconds) and into
`tools/ci/integration.sh` / `e2e.sh`; `select_suites_test.py` fails otherwise.
The selected shards are bin-packed into matrix legs; see "Job layout and runner
budget" below.

Selection rules (first match wins, see `RULES`):

- **Every non-E2E suite, the smoke leg and the mapped E2E leaves** for
  shared infrastructure: `.github/**`, `tools/ci/**`,
  `tools/testing/**`, `tools/seed|twenty|typst|surveys/**`, `infra/compose|locks|proxy/**`,
  `migrations/**`, `src/leonaid/platform|bootstrap|adapters/postgres/**`,
  `package.json`, `bun.lock`, `uv.lock`, `pyproject.toml`, `leonaid`,
  `tests/fixtures/**`, shared E2E configuration.
- **The same** for any path no rule maps (including the rest of `src/`, where
  the import graph adds its E2E leaves, and `apps/web|pwa|public`). Unknown
  means unsafe; map a path deliberately to make it cheaper.
- **No stack suite** for `*.md`, `*.mdx`, `apps/docs/**`, `specs/**` (except the
  OpenAPI approvals, EmDash route inventory and pilot plan files), `tests/unit/**`.
- **No stack suite** for the scripts and checkers of always-running jobs:
  `tools/ci/*_test.py`, `gate.py`, `workflow_contract.py`, `lint-types.sh`,
  `security.sh`, `build.sh`, `flake_summary.py`, the static gates
  (`conflict_markers.py`, `legacy_ui.py`, `no_test_doubles.py`, ...) and
  `reviewed_network_faults.json`; and for workflows that run no `ci.yml` suite
  (`docs.yml`, `docs-watchdog.yml`, `nightly-watchdog.yml`, `pin-drift.yml`,
  `release.yml`, `cache-benchmark.yml`). `surveys.yml`, `api-contract.yml`
  and `pins.yml` select only their own workflow. Gate data such as
  `infra/security/vulnerability-allowlist.json` selects only the pins
  workflow; Security judges it on every run anyway.
- **Only its suites** for a CI entry point: `tools/ci/e2e.sh` all E2E leaves,
  `integration.sh` all Integration shards plus Contract, `contract.sh`
  Contract, `emdash.sh` the EmDash proofs. Everything else in `.github/**` and
  `tools/ci/**` (`ci.yml`, the actions, `run-job.sh`, `free-runner-disk.sh`,
  `sanitize_artifacts.py`, `select_suites.py`, ...) is shared infrastructure.
- **Only the owning suite** for module and proof directories: the tasks module
  selects `E2E / tasks`; `tools/delivery/**` selects `Integration / delivery`;
  `apps/campaign-site/**`, `tools/emdash_spike/**` select the EmDash proofs;
  the survey module, package, demo app and `surveys-*` E2E specs select Surveys; `tools/<feature>/**` and
  `tests/e2e/<feature>.spec.mjs` select their E2E leaf. Helpers imported by
  other suites also select those (`tools/identity` and `tools/public_orders`
  start the EmDash proofs).
- API contract and dependency pins keep their former workflow path filters
  (`API_PATHS`, `PINS_PATHS`), now evaluated by the selector so the check
  always reports. Documentation and campaign-site changes no longer start the
  API stack.

Each gated workflow ends in one aggregate job: `CI gate`, `Survey gate`,
`API contract gate`, `Dependency pins gate`. `tools/ci/gate.py` reads
`toJSON(needs)` and fails unless the selector succeeded, every selected job
succeeded, every unselected job was skipped (not failed or cancelled) and every
other job succeeded. A skipped job therefore never hides an upstream failure.
These gates plus `Bilingual site artifact` (Documentation) are the required checks.
`.github/workflows/pin-drift.yml` dispatches exactly these workflows on its
re-pin branch, because its `GITHUB_TOKEN` PR starts none by itself; the
workflow contract fails when the two lists differ (`infra/locks/README.md`).
The former summary jobs (`Integration`, `E2E / <group>`, `EmDash proofs`,
`Surveys / <group>`) are gone: they repeated what the gate checks and each
took a runner slot per run. `workflow_contract.py` rejects them. `Golden
journey` stays, because it compares the two installations' results.

Dry-run the selector on any diff:

```sh
git diff --name-only --no-renames origin/main... > /tmp/paths
python3 tools/ci/select_suites.py --event pull_request --paths-file /tmp/paths --explain
```

### Infrastructure retries

Only infrastructure steps are retried; a test step never is.

- `tools/ci/retry-infra.sh` retries `./leonaid bootstrap`,
  `tools/ci/bootstrap-prefetch.sh` and `docker pull` (3 attempts, 15 s/30 s
  backoff). It refuses every other command, so a test cannot be wrapped by
  mistake.
- `.github/actions/build-cache`: a failed Docker bake / GitHub cache import
  (cache 429, registry errors) is retried once after 30 s.
- `.github/actions/test-fixture`: a failed fixture cache restore is retried once.
  `test-fixture.yml` verifies its cache upload and retries a missing upload once.

Every retry writes an `Infrastructure retry` warning annotation.
`workflow_contract.py` rejects `continue-on-error` in workflows, any other use of
"retry", and any first-attempt `continue-on-error` in the two actions without a
follow-up retry.

### Nightly run and flake summary

`ci.yml` runs completely on `main` every 3 hours (`37 */3 * * *`) and every night at 03:07 UTC; only the nightly run has the `Flake summary`. `surveys.yml` runs its PR selection every 3 hours (`47 */3 * * *`) and its nightly selection with the backup proofs at 01:17 UTC. The nightly `Flake summary`
job runs `tools/ci/flake_summary.py` over the last 50 completed runs of `ci.yml`
and `surveys.yml` (all events) and writes a table to the workflow summary:
failures in the final attempt and failures that were followed by a rerun
(the flake signal). Cancelled (superseded) jobs are ignored.

### Nightly watchdog

A red scheduled run has no pull request that shows it. `nightly-watchdog.yml`
runs after every scheduled run of `ci.yml`, `surveys.yml`, `pins.yml` and
`pin-drift.yml` on `main`, and once a day on its own schedule. For each
workflow it reads the latest completed scheduled run on `main`:

- not green: it opens the issue
  `[nightly-watchdog] <workflow> scheduled run needs attention` with the run
  link and the failed jobs, or adds one comment per new failed run;
- older than its limit (8 hours for the 3-hourly `ci.yml` and `surveys.yml`, 30 hours for `pin-drift.yml`, 8 days for the weekly `pins.yml`): the same
  issue reports a stopped schedule;
- green and current: it closes the issue.

It uses only `GITHUB_TOKEN` with `actions: read` and `issues: write`.
`tools/ci/workflow_contract.py` fails when a scheduled workflow is not watched.
`docs.yml` keeps its own `docs-watchdog.yml`.

### Required checks

The workflow side is above; the repository ruleset 26444840 (required gates,
no "require branch up to date") is applied by a maintainer. There is no merge
queue (personal-account repository); merges use merge commits, and the
scheduled runs on `main` test the merged result.

## Job layout and runner budget

The account runs at most 20 jobs at once. With several pull requests open,
runner slots, not test speed, decided the wall time: before this layout a
complete `ci.yml` run had 56 jobs (177 runner minutes, up to 27 minutes queue
per job), and each job spent about two minutes on checkout, build-layer import,
bootstrap, fixture restore and image pulls before its first test. Most of the
58 matrix legs ran two to four minutes of tests.

`ci.yml` therefore runs few, fat jobs:

| Job | Legs (complete run) | Content |
|---|---|---|
| `select`, `fixture` | 1 + 1 | Suite selection; synthetic fixture (a cache hit takes seconds) |
| Lint, types and unit | 1 | `tools/ci/lint-types.sh`, then `./leonaid test-unit` (also after a lint failure) |
| Build | 1 | Canonical Compose build; the only job that writes the BuildKit cache |
| Security | 1 | Policy checks and security stack test beside the vulnerability gate |
| `Integration / <shards>` | 4 | All Integration shards and Contract |
| `E2E / <leaves>` | 4 | All E2E leaves |
| `EmDash proof / <groups>` | 2 | `krapfentaxi-orders`; `krapfentaxi-migration` + `static` |
| Golden installation | 2 | Prepared and fresh installation (must stay separate runners) |
| Golden journey, CI gate | 1 + 1 | Result comparison; the required check |

That is 20 jobs instead of 56, 16 of them with a runner-heavy suite.
`select_suites.py` packs the selected shards with longest-processing-time-first
into at most `MAX_BINS` legs per kind, using the measured seconds in
`INTEGRATION_SECONDS` / `E2E_SECONDS`, and opens a further leg only per
`TARGET_SECONDS` (600 s) of tests. A pull request that touches two small leaves
gets one E2E leg. Legs have stable names (`Integration 1/4`, `E2E 2/4`,
`EmDash proof 1/2`) so the flake history stays comparable; the shard list is
in the job summary. The leg id names the artifact (`ci-integration-1`, ...).
The select job warns (`CI leg near timeout`) when a leg's estimate (shard
seconds, `LEG_SETUP_SECONDS` per leg and `SHARD_SETUP_SECONDS` per
Integration shard or EmDash group) passes 75 % of its `timeout-minutes`
(`JOB_TIMEOUT_MINUTES`, kept equal to `ci.yml` by `workflow_contract.py`);
`select_suites_test.py` keeps the complete run below 60 %.

Inside a leg every shard keeps its own isolation:

- `tools/ci/integration.sh a b c` runs each shard as before, each on its own
  fresh stack, and continues after a failure; the leg fails at the end and
  names every failed shard.
- `tools/ci/e2e.sh a b c` runs all leaves of one fixture kind (`golden`,
  `core`) in one `shared_stack.py --keep-going` call: the stack is built once,
  and the stopped fixture volumes are restored before every leaf, exactly as
  between the leaves of one shard before. A failed leaf does not stop the
  others; the exit code stays the first failure's.
- `tools/ci/emdash.sh a b` runs each group's cases once, without retries.
- After every shard, passed or failed (`tools/ci/run-shards.sh` for
  Integration and EmDash, `step()` in `e2e.sh`), `tools/ci/leak-check.sh`
  (CI runners only) compares the Compose projects before and after it. A shard that leaves
  containers, networks or volumes behind fails, and only its leaked projects
  are removed, so the next shard does not fail in its place.
- Every leg sets `LEONAID_CI_STEP_SECONDS` (5 minutes below its
  `timeout-minutes`). `tools/ci/capture-command.sh` runs the suite in its own
  process group and stops the whole group at that limit (SIGTERM, SIGKILL 30 s
  later), abandons output streams a stray descendant still holds, and exits
  124. `run-job.sh` then adds the last lines of every running container
  (`timeout-container-logs.txt`), sanitizes and uploads. A job killed by
  GitHub's own timeout would lose all of that.
- `tools/ci/disk-peak.sh` logs start, peak and end disk use of each leg, the
  data for the 40 GB skip threshold below.

On a fixture cache miss, `surveys.yml` waits up to 10 minutes for the
identical fixture key that `ci.yml`'s fixture job uploads for the same ref
(`test-fixture.yml` input `peer-wait-minutes`, polled through the Actions
cache API with `actions: read`) instead of building it a second time. If none
appears, it builds the fixture itself.

`surveys.yml` packs its 26 PR checks into 7 shards of about 8 minutes
(`tools/surveys/gate.json` `ciShards`); each check still gets fresh service
state.

Measured on PR #103 (run 42368175283, complete selection, busy runner pool):
19 jobs, 132 runner minutes, 112 queue minutes, longest job 12.8 min, legs of
7.6–11.6 min; Security 6.5 min (was 10.6). Before: 56 jobs, 177–214 runner
minutes, 385–461 queue minutes. `surveys.yml`: 11 jobs and 50 runner minutes
(was 26 jobs, 82 runner minutes).

A failed survey check prints a sanitized excerpt (failure lines, log tail
without Compose progress, foundation harness log) to the job log and uploads
it as `failure-excerpts.json` (`tools/surveys/ci_failure_excerpt.py`). The
repository is public, so redaction runs on the full text before any line is
cut: known secrets (`.env.local`, the run's `*.env` files, the prepared
fixture's Twenty key), then generic shapes (Authorization/Bearer,
Cookie/Set-Cookie and Playwright `{name, value}` cookie objects,
token/code/key/signature/X-Amz-* parameters, URL passwords, credential
assignments, login/invitation/verification codes, OTPs and PINs (de/en), JWTs,
and every base64url/hex run of 32+ characters except lower-case words joined
by `-`, `_` or `/`; a test proves 20 000 generated `token_urlsafe` values are
redacted).
Then `tools/ci/sanitize_artifacts.py` withholds the excerpt on personal data,
and a credential keyword still followed by a value withholds it too. Its
self-test runs in Lint, types and unit.

The heaviest single case, `krapfentaxi-orders` (about 12 minutes of tests),
sets the wall time of a complete run. `refit-timings.yml` (weekly, Monday 05:29 UTC) keeps the seconds tables
current: `tools/ci/refit_timings.py` reads the job logs of the last 7
successful nightly runs, takes per shard the median after dropping values
outside half to double of it, and opens a pull request (`ci/refit-timings`,
the required workflows dispatched like `pin-drift.yml`) only for entries
that moved by more than 15 %. Integration shards come from
`ci-integration: bin: <shard> passed (<n>s)`, E2E shards from the
`shared-stack:` / `ci-e2e: own leaf:` lines of their leaf scripts plus 30 s
of stack preparation, EmDash groups from `ci-emdash: OK: <case> (<n>s)`.

Cache write discipline: the shared BuildKit cache is written only by the
Build job of scheduled runs on `main` and dispatches; pull requests import
it read-only. The synthetic fixture is still saved by the run that misses
it (its key covers its inputs, so a pull request with a new migration needs
its own), and `surveys.yml` waits for `ci.yml`'s upload instead of building
it twice. Measured on run 42401453286: `./leonaid bootstrap` takes 20 s and
the build-layer import 24–67 s per leg; caching the installed `.venv` and
`node_modules` (830 MB together) would restore no faster than bootstrap
installs them, so there is no dependency cache.

Measured and decided against (2026-11-07, run 42405365220): leg setup is
bound by CPU and I/O contention on the 4-vCPU runner, not by downloads
(bootstrap 74 s in a leg, 20 s alone; the Twenty/Playwright prefetch of
53–74 s already runs beside it).

| Idea | Numbers | Decision |
|---|---|---|
| uv/bun dependency cache | `.venv` + `node_modules` 830 MB, bootstrap 20 s alone | skipped: no faster to restore |
| Third-party image tarball cache | images 1.7 GB (Playwright 1.0 GB), pull hidden behind bootstrap | skipped: no gain, 1.7 GB of the 10 GB cache budget |
| GHCR CI images by content hash | saves ~20–30 s of the in-step compose build per leg | deferred: needs a public package, cleanup and #122 (`ghcr.io/bjoernschotte/leonaid-ci/<service>:<tools/testing/image_tags.py hash>` agreed) |
| Split EmDash `krapfentaxi-orders` per browser | 3 legs ≈ 20 runner-min instead of 11, +2 jobs; wall −1 min (E2E legs are as long) | not done: every E2E leaf runs only nightly now |
| Concurrent light shards per leg | `disk-peak.sh` now logs memory peaks | open: decide from measured peaks |

## Integration and survey shards

Normal PR/main-push CI runs separate Integration shards for Compose cold start,
seed cold/idempotency, seed mutation/reset, Core, schema, outbox, storage, documents,
Typst, Twenty installation, CRM gateway, CRM import and policy. Pilot import includes a
real backup/restore and runs nightly instead. `bash tools/ci/integration.sh`
also excludes pilot import by default; that shard remains explicitly selectable.

Survey acceptance defines 39 checks in `tools/surveys/gate.json`: the two foundation diagnostics are separate entries, and the duplicate aggregate adapter run is consolidated.
PR checks occupy 7 shards of about 8 minutes each (`foundation`, `foundation-acceptance`,
`runner-permissions`, `editor-authoring`, `analysis-exports`, `lifecycle-contracts`,
`journeys-responses`), with compatible checks sharing one stack; the six nightly
shards still contain 13 checks, with no overlap or missing checks. Nightly-only shards are:

- recovery-deletion, recovery-retention, recovery-restic and recovery-pilot;
- exports-recovery, including its state/limit checks;
- restore-receipts, previously part of foundation.

`.github/workflows/surveys.yml` runs the nightly selection daily at 01:17 UTC
(02:17 CET / 03:17 CEST). GitHub schedules start only after the workflow is on
`main`. PRs and ordinary main pushes never select these nightly shards, even
when backup code changes. Manual dispatch offers `pr`, `nightly` and `all`.
The nightly workflow also runs test-backup, test-upgrade, test-pilot-backup,
test-pilot-deployment, test-pilot-install, test-pilot-import and
test-pilot-release on separate runners. These cover full restore, upgrade
rollback, the backup target, the first install on an empty host and pilot
restore/release paths. Each selected test runs once.

`Survey gate` requires every shard selected for that event to succeed. It
does not claim that nightly-only checks executed in a PR. A selected shard's
failure, cancellation or skipping cannot produce a green gate. The entire
nightly workflow fails if either a survey shard or a standalone backup job fails.

Normal domain/unit tests, seed reset, migration checks and individual
retry/restart assertions within feature tests stay in PR CI. They are not
full backup/restore rehearsals. Explicit local commands still run the full
requested selection, independent of the CI schedule.

```sh
./leonaid test-surveys --shard lifecycle-contracts
./leonaid test-surveys --group recovery
```

## EmDash proofs

The optional campaign site (Compose profile `emdash`) has its own proof cases
(`./leonaid test-emdash-spike --case <name>`). Two regressions were only visible
in them: an EmDash editor load race (PR #37) and a Caddy body-drain regression
(PR #38). PR and main CI therefore run `tools/ci/emdash.sh` in the
`EmDash proof / <groups>` matrix, gated by `CI gate`. Two legs
(`EMDASH_BINS`): `krapfentaxi-orders` alone, `krapfentaxi-migration` with `static`.

| Group | Cases |
|---|---|
| `krapfentaxi-orders` | `krapfentaxi-orders`: Krapfentaxi import, Chromium/Firefox/WebKit editor and order journeys, Core/Twenty order ingress, native order deadlines |
| `krapfentaxi-migration` | `krapfentaxi-migration`: Krapfentaxi import with original media, three-browser editor and renderer proof, published redirects; `redirect-aliases`: Chromium/Firefox/WebKit redirect alias editor (create, disable/enable, collision, move, remove) under the strict CSP |
| `static` | stack-free `dependencies`, `krapfentaxi-source`, `authorization-inventory`, `release-manifest-compatibility`, `release-legacy-boundary`, `release-image-identity`, `closed-runtime`; plus `proxy-routing` (Caddy, public and CMS only, no database) |

The jobs need no prepared fixture: every case builds its own isolated stack and
seeds synthetic data. The scheduled runs on `main` always run them. In a pull request the selector starts them for EmDash inputs and for every
shared Core, proxy or public change (see "Tiers" above); there is no
workflow path filter. Each case runs exactly once. Neither the script nor the
workflow retries a failed case, so an intermittent failure stays red and must
be fixed at its cause. `tools/ci/workflow_contract.py` rejects a missing group,
a path filter, `continue-on-error` or a retry in the job.

Observed GitHub runtimes (PR #40, run 42360553738): `krapfentaxi-orders`
12–15 min, `krapfentaxi-migration` 4–6 min, `static` 1–3 min.
`krapfentaxi-orders` is one stateful case (import, three-browser commerce
phases, Twenty start, order journeys) and remains the longest job of the run;
the other legs are packed to finish before it.

The jobs import the `emdash` BuildKit group; the Build job also exports the
`campaign-site` cache. On failure the harness stores `compose ps` and the
overlay-complete Compose log of each failed project under
`runtime-<project>/`, sanitized against `.env.local` and the run's own order
and CRM keys. Of a proof directory only text files are copied: `*.env` files
hold live session tokens, and screenshots, PDFs and other binaries are listed
by name in `proof-omitted.txt` instead, because the sanitizer would reject them
and discard the whole capture.

The remaining cases stay local-only. They duplicate the two Krapfentaxi stacks
in large parts, need further runner time each, or prove nightly recovery flows.

## One environment per compatible group

`tools/testing/shared_stack.py` builds the Compose images once per group, using
Docker's available layer cache. It starts the real services, migrates Core,
provisions Twenty once for Golden-based groups, and renders the fixed PDF
fixtures once. It records a **job-local, stopped-volume fixture** before any
feature test seeds data. Each leaf then starts the services it needs and runs
its original seed, API assertions and browser tests in sequence.

Sharing applies to E2E identity, acquisition, actions and public; Integration
storage/documents/Typst; CRM gateway/import; and compatible survey infrastructure
and lifecycle-concurrency checks within one aggregate pass. Documents run only
in Integration, including their browser coverage. The real OpenAPI contract
runs only in the dedicated API contract workflow. Direct shell-script invocations keep their original owned setup and teardown.
In CI, single-check survey selections do not pay for a snapshot. Local CLI
commands use the persistent fixture described below.

### Why seeding alone is insufficient

Golden seeding upserts known Core/Twenty fixtures. It does not remove all new
contacts, users, sessions, assignments, surveys or events from earlier tests.
Storage seeding only cleans its prefix and does not remove old object versions
or delete markers. Seed-core also does not empty Mailpit.

Between leaves the owner stops the group's services, restores all its initialized
volumes, then lets the next leaf seed its required data. This resets:

| State | Reset boundary |
|---|---|
| Core and Twenty PostgreSQL | Entire stopped database volumes, including schemas, sequences and extra rows |
| Valkey / Twenty queues | Initial queue/cache volume; processes restart without stale in-memory work |
| RustFS / SeaweedFS | Entire initialized object store, including versions and delete markers |
| Mailpit | Initial empty mail database |
| Twenty local files, maintenance state, survey erasure archive | Initial owned volume contents |
| API / worker caches and in-flight transactions | Stop before copying, restart after reset |
| Browser sessions, cookies and service workers | A new Playwright process/container and private proof directory per leaf |

Images and networks are retained. Containers are reused; Compose may recreate
an application container if a leaf explicitly changes its configuration (for
example the short fresh-login interval). Health checks and process startup still
cost time, but build, initial database installation and CRM provisioning no
longer repeat per feature. Twenty also skips repeated upgrade/cache-flush and
cron-registration commands after the first initialization; the fixture already
contains that schema and the registered Valkey (BullMQ) jobs. Test writers get a bounded
five-second stop window before resetting their discarded state. Locally captured fixtures remain private. CI can import the explicitly generated
synthetic-only template described below; no development/runtime snapshot is exported. This does not exercise the application's backup feature;
backup/recovery acceptance remains nightly.

### Concurrent runs and exceptional tests

Every invocation uses an unpredictable project name, a private directory/token,
its own volumes and reserved non-overlapping networks, without published ports.
All resource inventories must be empty before taking ownership. Copying refuses
running services or a changed volume inventory. An atomic per-fixture lease
excludes both another leaf and a reset while a leaf is active. Only the parent
resets and tears down its own group; a borrowed leaf never deletes the stack.
Independent jobs/worktrees can run concurrently without sharing data or resets.
The survey gate additionally retains its checkout-wide lock for shared artifacts.

Compose/Core cold-start, schema predecessor/empty database, seed/reset and
Twenty first-provisioning/drift tests retain their independent environments.
The small standalone aggregate engine and outbox worker-process tests also
retain their focused harnesses. Nightly recovery harnesses remain independent.
In CI, explicit survey repeat passes create a new fixture and project each time.
No global Docker pruning or reset is used.

Every owned suite ends its teardown with `verify_owned_project_removed`
(`tools/testing/owned_teardown.sh`; `SharedStack.remove_owned` in Python). It
lists any container (also stopped `compose run` one-offs), network or volume
that still carries the project's Compose label, removes exactly those and fails
the run, so a leak is visible but cannot exhaust Docker's address pools. It
also removes the `<project>-<service>` images Compose built, because project
names are unique per run and those images are never reused.
`tools/ci/capture-failure.sh` reads the Compose file set from the project's
containers instead of assuming `compose.yml`: a different file set made its
`compose run api` create networks the suite's `down` did not know.

Validation commands:

```sh
python3 tools/testing/shared_stack_test.py
python3 tools/testing/shared_stack_live.py
python3 tools/testing/owned_teardown_live.py
sh tools/ci/e2e.sh acquisition
./leonaid test-surveys --shard lifecycle-contracts
```

The live reset proof deliberately contaminates both databases, Valkey, versioned
storage and mail, rejects a reset while a leaf lease is held, and verifies the
clean state with the same containers and volumes afterward. Group logs separate
initial setup, data reset and each leaf's runtime. Compare new GitHub runtimes
on the same runner class; local warm/cold-cache measurements are not CI forecasts.

PR #4 baseline: Integration 37:52; Surveys / exports 34:35. The export group's
second pass alone took 14:57. These are observed baseline times, not a promise
of the new workflow's duration. Compare wall time and total runner minutes
after running the new workflow; additional runners trade parallel capacity
for shorter feedback time.

## Local development

Normal `./leonaid test-integration` and `./leonaid test-e2e` have disjoint
script inventories and never invoke backup/upgrade acceptance. Integration owns
cold infrastructure/schema checks, CRM contracts, policy, templates, storage,
documents/Typst and testkit. E2E owns the remaining feature/browser groups and the
standalone Golden Journey. The latter deliberately proves fresh installations.
Mail relay and cold infrastructure tests also retain their specialized setup.

Compatible individual commands (for example `./leonaid test-actions`) and
aggregates automatically reuse a private fixture under `.local/test-stack`.
The first call installs it; later calls reset its data and seed the next test.
Application input changes rebuild images with Docker's layer cache. Changes to
migrations, Compose, environment, pinned images or fixture/provisioning inputs
invalidate and initialize the data fixture again. This is synthetic test data,
not an application backup/restore test. When the invocation ends, the fixture's
containers are stopped (volumes, images and the saved data stay), so an idle
checkout holds no Twenty, database or application memory.

The existing development stack is never adopted or reset. The test fixture uses
its own project, volumes and networks without host ports. One process holds the
checkout lock for the whole invocation; another local test refuses immediately
instead of resetting running tests. Different worktrees remain independent.

```sh
./leonaid test-actions             # cache-backed targeted feature test
./leonaid test-e2e                 # sequential features, reset between each
./leonaid test-env-stop            # remove only this checkout's test fixture
LEONAID_TEST_FRESH=1 ./leonaid test-actions  # isolated fresh setup and teardown
./leonaid test-recovery            # explicitly run backup/recovery acceptance
./leonaid test-surveys --suite nightly
```

Survey defaults select the 26 PR checks; `--suite all`, `--suite nightly`,
`--group recovery` or an explicit nightly shard opt into recovery. Compatible
local survey checks use the same locked fixture. CI always uses ephemeral
job-local writable fixtures. Only their synthetic initialization template is cached.

## Persistent GitHub BuildKit cache

The local composite action `.github/actions/build-cache` prepares a job-local
Buildx builder from GitHub cache v2, then selects that same builder for subsequent
Compose builds. Normal jobs materialize imported layers through an OCI export discarded at
`/dev/null`, then load images once when the test harness builds its runtime tags.
A cache-only export leaves lazy imported records that the subsequent Compose
build did not reuse in our GitHub measurement; it must not replace this export. Only the explicit cache
benchmark enables `load: "true"` to retain its warm-tag runtime probe. Project-specific image names remain independent; initialized
volumes, secrets and runtime state are never exported.

Scopes are stable per image family and `linux/amd64`; BuildKit invalidates layers
from Dockerfile and source inputs. API and worker share the Core cache. Only the
normal Build job exports the production cache. Other image-consuming jobs import
it without concurrent writes. Explicit `cold_run` jobs bypass this action.
Survey sudo invocations preserve CI and the selected Docker builder/configuration.

The opt-in Build cache benchmark (manual dispatch or the
`benchmark-build-cache` pull-request label) uses fresh GitHub runners for
proxy-only and full-image scenarios, in three sequential rounds: cold without
imports, unchanged with imports, and a comment-only Public source change with
imports. Its cache namespace includes the workflow run ID and cannot alter the
normal cache. Reports include builder preparation/import/build/export/load time
and a subsequent project-renamed Compose build. The latter must cache every
Dockerfile RUN step. Full-image cases also start the real Public Node image and
verify its HTTP readiness. No database or test stack is needed for this benchmark.

## Runner disk budget

GitHub-hosted `ubuntu-24.04` runners differ: AWS-hosted ones have a 72 GB disk
with about 14 GB free, Azure-hosted ones 145 GB with 86 GB free. Every job
that builds or loads LeonAid images therefore runs
`tools/ci/free-runner-disk.sh start` right after checkout and
`tools/ci/free-runner-disk.sh wait` right before its suite. Deletion overlaps
cache import and fixture restore and frees about 18 GB. `start` skips the
deletion when at least `LEONAID_FREE_DISK_MIN_GB` (default 40) GB are free:
on Azure runners the deletion only cost 30–120 s of metadata I/O.

The Security job builds all own images and scans every pinned third-party
image on one runner. Measured on an Azure runner (145 GB disk), the job
consumes about 19 GB: Playwright image 2.7 GB, Trivy and Java advisory DBs
3.3 GB, own images about 7 GB (daemon images plus the Buildx builder volume),
third-party images about 3 GB. Hosted runners differ in free disk; an AWS
runner ran out while building the own images.

- `tools/ci/free-runner-disk.sh start|wait` deletes preinstalled toolchains
  LeonAid never uses (Android SDK, .NET, GHC, CodeQL) in the background, in
  parallel per subdirectory. It refuses to run outside GitHub Actions.
- `tools/security/pulled-images.sh` removes a pinned image right after its use
  only when that exact digest was absent before. Locally present images,
  including any other tags of the same image, stay untouched.
- `LEONAID_CI_DISK_REPORT=1` makes the scan log `tools/ci/disk-report.sh`
  output after every phase (start, advisory databases, own images built, all
  targets scanned). The per-target reports cost about 45 s per run.
- In CI, `tools/ci/security.sh` runs the vulnerability gate beside the policy
  checks and the security stack test (`LEONAID_SCAN_KEEP_PULLED=1`: the
  third-party images stay until the job ends, because the stack may use them).
  The scan pulls the third-party images in the background while the advisory
  databases download and the own images build; each image is pulled again
  right before its scan, so a failed head start cannot skip a target. The gate
  still requires a report for every target on every event.

`tools/ci/workflow_contract.py` requires both steps in every job that uses the
build cache (except the single-image API contract and SBOM jobs), in the cold
rehearsal and in the nightly recovery proofs.

## Five-minute workflow budget

The next optimization stage prepares a synthetic initialization template in
`test-fixture.yml`. Its exact cache key covers schema, application initialization
inputs, tool versions and fixture code. A miss rebuilds it in an isolated source
copy without reading `.env.local`, `.local`, artifacts or existing Docker volumes.
All credentials are deliberately synthetic and generated from `.env.example`.
The template contains initialized stopped volumes, fixed PDF fixtures and its own
synthetic CRM integration token. It never contains feature-test mutations.

Each consumer verifies provenance, input key, file digests and archive paths;
links and devices in archives are rejected. It then materializes a fresh set of
project-owned volumes. No consumer mounts the cache writable. Existing leases and
inventory guards still exclude concurrent reset/use. Local development continues
to use its private checkout fixture; CI activation cannot overwrite a local
worktree's environment.

Functional E2E groups and survey checks run in bins on independent runners
(see "Job layout and runner budget"). Long legs appear first in each matrix;
GitHub creates jobs in matrix order but does not guarantee start order.
Survey pairs are lifecycle/contracts, request-limits/concurrency,
responses/payload-limits, preview/branding, and analysis/export-permissions.
The single aggregate adapter joins the independent foundation harnesses.
Each paired service check finishes and releases its lease before its owner
resets the private fixture and starts the next check. No reset overlaps tests. Short E2E
pairs share initialization with a guarded reset between leaves: invitations and
sessions, actions and templates, assignments and activities, public actions and
activity feed. Schema/outbox share a runner; the Survey package check joins foundation.
The aggregate adapter runs once alongside the standalone foundation checks
against the production validator image, including real stop/start failure handling; it needs no
database, prepared fixture, frontend or browser. This avoids queuing dozens of one-leaf jobs. Optional Compose
profiles are independent of the genuine cold-start/restart persistence check.
Survey Runner browser coverage and its durable-operation verification now belong
only to the runner check, not also to contracts. Passing/failing infrastructure
browser diagnostics run in independent jobs and retain their teardown and secret
scan assertions. The Survey profile starts admin/public frontends without the
PWA except in Journey, whose member probe follows the /admin/ to /app/
redirect; API readiness continues to check its real dependencies.
The four Journey cases run with two browser workers, each owning its survey,
recipients and proof files. Authoring, responses, exports and deletion stay
sequential within a case. No reset happens between concurrent cases; the owner
holds its fixture lease until all cases and final SQL/object checks finish.
Journey and permissions prefetch Twenty and Playwright while bootstrap runs.

Golden Journey compares the digest of normalized first-round results from a
prepared environment (two functional rounds) and an independent fresh installation
(one round). Session files and business reports do not cross jobs. Seed acceptance
separates cold installation/idempotency from mutation/real operator reset: only
the latter's starting state comes from the template; the tested reset still
creates empty volumes through the unchanged operator CLI.

The budget is 40s for images/tools, 50s for services/data, 150s for tests, 30s for
cleanup/reporting and 30s reserve. It is a target, not a timeout that hides failures.
A new template build and GitHub queue time are included when reporting complete
workflow time, and must be measured separately from a warm template hit. Increasing
parallel groups requires corresponding runner capacity. Cold installation and
migration checks remain enabled; no coverage is moved out of PR CI to meet a number.
