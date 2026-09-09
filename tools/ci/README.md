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

Within a locked survey aggregate, infrastructure checks reuse images built
from that checkout. Image names are scoped to the private run directory;
later checks use `--no-build`. The cache contains only image-name overrides,
not rendered Compose configuration, credentials or runtime data. Builds must
succeed before the cache is marked ready. Missing images fail the check.

Every check still owns fresh containers, networks and volumes and verifies
their teardown. Standalone infrastructure calls and foundation cold-build
checks keep their full build path. A new aggregate (or explicit repeat pass)
gets a new image namespace. Generated images remain local, like other test
builds, and are discarded with the ephemeral GitHub runner. No global Docker
pruning or shared database snapshots are introduced.

PR #4 baseline: Integration 37:52; Surveys / exports 34:35. The export group's
second pass alone took 14:57. These are observed baseline times, not a promise
of the new workflow's duration. Compare wall time and total runner minutes
after running the new workflow; additional runners trade parallel capacity
for shorter feedback time.
