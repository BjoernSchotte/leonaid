#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
source_project="leonaid-poc112-surveys-$suffix"
target_project="leonaid-restore-surveys-$suffix"
mkdir -p "$root/.artifacts"
# Restore overlays must be inside the checkout. This private temporary directory
# is ignored by git and removed by the trap, including all credentials/backups.
proof=$(mktemp -d "$root/.artifacts/survey-restic.XXXXXX")
source_owned=false
target_owned=false
source_compose() {
  docker compose --project-name "$source_project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" --file "$proof/source.yml" \
    --profile dev-mail "$@"
}
target_compose() {
  docker compose --project-name "$target_project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" --file "$proof/target.yml" \
    --file "$proof/images.json" --profile dev-mail "$@"
}
cleanup() {
  status=$?
  if [ "$source_owned" = true ]; then
    source_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  if [ "$target_owned" = true ]; then
    target_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
for project in "$source_project" "$target_project"; do
  [ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]
  [ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ]
done
python3 "$root/tools/surveys/network_override.py" "$proof/source.yml"
source_owned=true
source_compose up --build --detach --wait --wait-timeout 420 proxy worker mailpit
source_compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --workdir /repo --entrypoint python api tools/surveys/infrastructure.py
source_compose stop worker
probe() {
  runner=$1
  shift
  "$runner" run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/recovery_live.py "$@"
}
probe source_compose seed
# Pin all built services to the actual source image IDs. No target-side build,
# mutable registry lookup or silent fallback may change them during restoration.
python3 - "$source_project" "$proof" <<'PY'
import json, pathlib, secrets, subprocess, sys
project, directory = sys.argv[1], pathlib.Path(sys.argv[2])
services = {}
for service in ('api', 'worker', 'web', 'pwa', 'public', 'survey-validator'):
    image = subprocess.check_output(
        ['docker', 'image', 'inspect', '--format', '{{.Id}}', f'{project}-{service}'], text=True
    ).strip()
    services[service] = {'image': image}
(directory / 'images.json').write_text(json.dumps({'services': services}))
password = directory / 'restic-password'
password.write_text(secrets.token_urlsafe(48) + '\n')
password.chmod(0o600)
PY
LEONAID_COMPOSE_PROJECT="$source_project" \
  LEONAID_BACKUP_COMPOSE_OVERLAY="$proof/source.yml" \
  LEONAID_BACKUP_REPOSITORY="$proof/repository" \
  LEONAID_BACKUP_PASSWORD_FILE="$proof/restic-password" \
  LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
  LEONAID_BACKUP_MANIFEST_OUTPUT="$proof/backup-manifest.json" \
  sh "$root/tools/backup/backup.sh" "$root"
source_compose up --detach --wait --wait-timeout 420 proxy mailpit
probe source_compose delete
source_compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --workdir /repo --entrypoint python api tools/surveys/recovery.py export \
  --output /proof/recovery-checkpoint.json
# Source DB, object volume and containers are gone before either target restore.
# The manually exported checkpoint survives separately; automatic latest-file
# continuity across loss of this host is deliberately not claimed by this test.
source_compose down --volumes --remove-orphans
[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$source_project")" ]
[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$source_project")" ]
python3 "$root/tools/surveys/network_override.py" "$proof/target.yml"
cutoff=$(cat "$proof/recovery-cutoff.txt")
restore() {
  LEONAID_BACKUP_SOURCE_PROJECT="$source_project" \
    LEONAID_RESTORE_PROJECT="$target_project" \
    LEONAID_RESTORE_CONFIRM="RESTORE:$target_project" \
    LEONAID_BACKUP_REPOSITORY="$proof/repository" \
    LEONAID_BACKUP_PASSWORD_FILE="$proof/restic-password" \
    LEONAID_BACKUP_ALLOW_LOCAL_TEST=true \
    LEONAID_RESTORE_COMPOSE_OVERLAY="$proof/target.yml" \
    LEONAID_RESTORE_COMPOSE_OVERLAY_SECONDARY="$proof/images.json" \
    LEONAID_RESTORE_NO_BUILD=true \
    LEONAID_RESTORE_START_APP=true \
    LEONAID_SURVEY_ERASURE_CHECKPOINT="$1" \
    LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH="$cutoff" \
    sh "$root/tools/backup/restore.sh" "$root"
}
target_owned=true
bad_status=0
restore '' || bad_status=$?
[ "$bad_status" -eq 1 ] || { echo 'Expected missing-checkpoint restore failure' >&2; exit 1; }
for service in api public proxy worker; do
  [ -z "$(target_compose ps --status running --quiet "$service")" ]
done
# A real restored survey and its original object must exist: failure before
# restoration (e.g. a bad manifest) cannot masquerade as successful gate coverage.
probe target_compose restored
target_compose down --volumes --remove-orphans
[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$target_project")" ]
restore "$proof/recovery-checkpoint.json"
probe target_compose online-restic
python3 - "$target_project" "$proof" <<'PY'
import json, pathlib, subprocess, sys
project, directory = sys.argv[1], pathlib.Path(sys.argv[2])
for service, config in json.loads((directory / 'images.json').read_text())['services'].items():
    actual = subprocess.check_output(
        ['docker', 'inspect', '--format', '{{.Image}}', f'{project}-{service}-1'], text=True
    ).strip()
    assert actual == config['image'], service
PY
docker run --rm --network "${target_project}_edge" --env-file "$proof/session.env" \
  --env HOME=/tmp --env CI=1 --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" --workdir /workspace "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test tests/e2e/surveys-infrastructure.spec.mjs \
  --browser=chromium --output=/proof/test-results --reporter=line
target_compose down --volumes --remove-orphans
[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$target_project")" ]
[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$target_project")" ]
mkdir -p "$root/.artifacts/surveys-restic"
python3 - "$proof/restic-recovery-proof.json" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
result = json.loads(path.read_text())
result.update({
    'existingResticBackupRotationAndReadDataCheck': True,
    'sourceContainersAndVolumesRemovedBeforeRestore': True,
    'missingCheckpointBlocksActualFreshTargetRestore': True,
    'rejectionLeavesOldSurveyAndExactObjectOffline': True,
    'validCheckpointAllowsFullNoBuildApplicationStartup': True,
    'allBuiltServiceImageIdsMatchSource': True,
    'foundationChromiumPassed': True,
    'targetTeardownVerified': True,
})
path.write_text(json.dumps(result, indent=2) + '\n')
PY
cp "$proof/restic-recovery-proof.json" "$root/.artifacts/surveys-restic/"
echo "PASS: real encrypted Restic backup/rotation/check, source removal, fresh-target rejection and no-build recovery: $suffix"
