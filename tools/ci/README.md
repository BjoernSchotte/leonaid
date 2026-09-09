# CI runtime

Normal PR/main-push CI runs separate Integration shards for Compose cold start,
seed cold/idempotency, seed mutation/reset, Core, schema, outbox, storage, documents,
Typst, Twenty installation, CRM gateway, CRM import and policy. Pilot import includes a
real backup/restore and runs nightly instead. `bash tools/ci/integration.sh`
also excludes pilot import by default; that shard remains explicitly selectable.

Survey acceptance keeps the original 39 checks and splits the two foundation diagnostics into separate checks in `tools/surveys/gate.json`.
PR shards now assign individual functional checks independently; the six nightly
shards still contain 13 checks, with no overlap or missing checks. Nightly-only shards are:

- recovery-deletion, recovery-retention, recovery-restic and recovery-pilot;
- exports-recovery, including its state/limit checks;
- restore-receipts, previously part of foundation.

`.github/workflows/surveys.yml` runs the nightly selection daily at 01:17 UTC
(02:17 CET / 03:17 CEST). GitHub schedules start only after the workflow is on
`main`. PRs and ordinary main pushes never select these nightly shards, even
when backup code changes. Manual dispatch offers `pr`, `nightly` and `all`.
The nightly workflow also runs test-backup, test-upgrade, test-pilot-backup,
test-pilot-deployment, test-pilot-import and test-pilot-release on separate
runners. These cover full restore, upgrade rollback, the backup target and
pilot restore/release paths. Each selected test runs once.

Existing `Surveys / <group>` check names remain conservative policy summaries:
every shard selected for that event must succeed. They do not claim that
nightly-only checks executed in a PR. A selected shard's failure, cancellation
or skipping cannot produce a green summary. The entire nightly workflow fails
if either a survey shard or a standalone backup job fails.

Normal domain/unit tests, seed reset, migration checks and individual
retry/restart assertions within feature tests stay in PR CI. They are not
full backup/restore rehearsals. Explicit local commands still run the full
requested selection, independent of the CI schedule.

```sh
./leonaid test-surveys --shard request-limits
./leonaid test-surveys --group recovery
```

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
| Redis / Twenty queues | Initial queue/cache volume; processes restart without stale in-memory work |
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
contains that schema and the registered Redis jobs. Test writers get a bounded
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

Validation commands:

```sh
python3 tools/testing/shared_stack_test.py
python3 tools/testing/shared_stack_live.py
sh tools/ci/e2e.sh acquisition
./leonaid test-surveys --shard request-limits
```

The live reset proof deliberately contaminates both databases, Redis, versioned
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
not an application backup/restore test.

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

Survey defaults select the 27 PR checks; `--suite all`, `--suite nightly`,
`--group recovery` or an explicit nightly shard opt into recovery. Compatible
local survey checks use the same locked fixture. CI always uses ephemeral
job-local writable fixtures. Only their synthetic initialization template is cached.

## Persistent GitHub BuildKit cache

The local composite action `.github/actions/build-cache` prepares a job-local
Buildx builder from GitHub cache v2, then selects that same builder for subsequent
Compose builds. Project-specific image names remain independent; initialized
volumes, secrets and runtime state are never exported.

Scopes are stable per image family and `linux/amd64`; BuildKit invalidates layers
from Dockerfile and source inputs. API and worker share the Core cache. Only the
normal Build job exports the production cache. Other image-consuming jobs import
it without concurrent writes. Explicit `cold_run` jobs bypass this action.
Survey sudo invocations preserve CI and the selected Docker builder/configuration.

The opt-in/path-triggered Build cache benchmark uses fresh GitHub runners for
proxy-only and full-image scenarios, in three sequential rounds: cold without
imports, unchanged with imports, and a comment-only Public source change with
imports. Its cache namespace includes the workflow run ID and cannot alter the
normal cache. Reports include builder preparation/import/build/export/load time
and a subsequent project-renamed Compose build. The latter must cache every
Dockerfile RUN step. Full-image cases also start the real Public Node image and
verify its HTTP readiness. No database or test stack is needed for this benchmark.


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

Functional E2E leaves and survey checks run independently on separate runners.
Survey Runner browser coverage and its durable-operation verification now belong
only to the runner check, not also to contracts. Passing/failing infrastructure
browser diagnostics run in independent jobs and retain their teardown and secret
scan assertions. The Survey profile starts admin/public frontends without the
unused PWA; API readiness continues to check its real dependencies.

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
