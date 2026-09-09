# CI runtime

Normal PR/main-push CI runs six Integration shards: Compose cold start,
seed/reset, Core, documents/storage, CRM and policy. Pilot import includes a
real backup/restore and runs nightly instead. `bash tools/ci/integration.sh`
still executes all 13 original scripts locally, including pilot import.

Survey acceptance keeps every one of the 39 checks in `tools/surveys/gate.json`.
Its 17 shards are partitioned into 11 PR shards (26 checks) and six nightly
shards (13 checks), with no overlap or missing checks. Nightly-only shards are:

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
./leonaid test-surveys --shard integration-limits
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
runs only in the dedicated API contract workflow. Standalone leaf commands keep
their original owned setup and teardown. Single-check survey selections do not
pay for a snapshot.

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
five-second stop window before resetting their discarded state. The private fixture is never uploaded or cached
between CI runs. This does not exercise the application's backup feature;
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
Explicit survey repeat passes create a new fixture and project each time.
No global Docker pruning or reset is used.

Validation commands:

```sh
python3 tools/testing/shared_stack_test.py
python3 tools/testing/shared_stack_live.py
sh tools/ci/e2e.sh acquisition
./leonaid test-surveys --shard integration-limits
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
