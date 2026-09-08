#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
mode=${2:-manual}
case "$mode" in manual|archive|durable) ;; *) echo 'Expected manual, archive or durable mode' >&2; exit 1 ;; esac
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
source_project="leonaid-poc112-surveys-$suffix"
target_project="leonaid-restore-surveys-$suffix"
archive_volume="leonaid-survey-archive-$suffix"
archive_owned=false
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
verify_project_absent() {
  checked_project=$1
  for inventory in containers volumes networks; do
    case "$inventory" in
      containers) remaining=$(docker ps -aq --filter "label=com.docker.compose.project=$checked_project") || return 1 ;;
      volumes) remaining=$(docker volume ls -q --filter "label=com.docker.compose.project=$checked_project") || return 1 ;;
      networks) remaining=$(docker network ls -q --filter "label=com.docker.compose.project=$checked_project") || return 1 ;;
    esac
    if [ -n "$remaining" ]; then
      echo "survey-restic: owned $inventory remain for $checked_project" >&2
      return 1
    fi
  done
}
cleanup() {
  status=$?
  if [ "$source_owned" = true ]; then
    source_compose down --volumes --remove-orphans >/dev/null 2>&1 || status=1
    verify_project_absent "$source_project" || status=1
  fi
  if [ "$target_owned" = true ]; then
    target_compose down --volumes --remove-orphans >/dev/null 2>&1 || status=1
    verify_project_absent "$target_project" || status=1
  fi
  if [ "$archive_owned" = true ]; then
    docker volume rm "$archive_volume" >/dev/null 2>&1 || status=1
    remaining=$(docker volume ls -q --filter "name=^${archive_volume}$") || status=1
    if [ -n "$remaining" ]; then status=1; fi
  fi
  if [ "$status" -eq 0 ]; then echo 'survey-restic: owned source/target containers, volumes, networks and archive volume removed'; fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
for project in "$source_project" "$target_project"; do
  existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
  [ -z "$existing" ]
  existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
  [ -z "$existing" ]
  existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
  [ -z "$existing" ]
done
if [ "$mode" != manual ]; then
  existing=$(docker volume ls -q --filter "name=^${archive_volume}$")
  [ -z "$existing" ]
  docker volume create --label "leonaid.survey-recovery-proof=$suffix" "$archive_volume" >/dev/null
  archive_owned=true
fi
if [ "$mode" = durable ]; then
  python3 "$root/tools/surveys/network_override.py" "$proof/source.yml" "$archive_volume"
else
  python3 "$root/tools/surveys/network_override.py" "$proof/source.yml"
fi
source_owned=true
source_compose up --build --detach --wait --wait-timeout 420 proxy worker mailpit
source_compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --workdir /repo --entrypoint python api tools/surveys/infrastructure.py
source_compose stop worker
probe() {
  runner=$1
  shift
  probe_service=api
  if [ "$1" = durable-delete ]; then probe_service=worker; fi
  "$runner" run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python "$probe_service" tools/surveys/recovery_live.py "$@"
}
probe source_compose seed
archive_publish() {
  source_compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --volume "$archive_volume:/archive" --workdir /repo --entrypoint python api \
    tools/surveys/recovery.py publish --archive /archive
}
if [ "$mode" = archive ]; then archive_publish; fi
# Pin all built services to the actual source image IDs. No target-side build,
# mutable registry lookup or silent fallback may change them during restoration.
python3 - "$source_project" "$proof" <<'PY'
import json, pathlib, secrets, subprocess, sys
project, directory = sys.argv[1], pathlib.Path(sys.argv[2])
services = {}
for service in ('api', 'worker', 'web', 'pwa', 'public', 'survey-validator', 'proxy'):
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
if [ "$mode" = durable ]; then probe source_compose durable-delete; else probe source_compose delete; fi
cutoff=$(cat "$proof/recovery-cutoff.txt")
if [ "$mode" != manual ]; then
  if [ "$mode" = durable ]; then
    installation=$(cat "$proof/recovery-installation.txt")
  else
    installation=$(python3 - "$proof/recovery-checkpoint.json" <<'PY'
import json, sys
with open(sys.argv[1]) as source:
    print(json.load(source)['checkpoint']['installation_id'])
PY
)
  fi
  api_image=$(python3 - "$proof/images.json" <<'PY'
import json, sys
with open(sys.argv[1]) as source:
    print(json.load(source)['services']['api']['image'])
PY
)
  archive_fetch() {
    docker run --rm --network none --env-file "$root/.env.local" \
      --volume "$root:/repo:ro" --volume "$proof:/proof" --volume "$archive_volume:/archive" \
      --workdir /repo --entrypoint python "$api_image" tools/surveys/recovery.py fetch \
      --archive /archive --output /proof/fetched-checkpoint.json \
      --installation-id "$installation" --required-through "$cutoff"
  }
  if [ "$mode" = archive ]; then
  status=0
  archive_fetch || status=$?
  [ "$status" -eq 1 ] && [ ! -e "$proof/fetched-checkpoint.json" ]
  for boundary in after-pending after-current; do
    status=0
    source_compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
      --volume "$archive_volume:/archive" --workdir /repo --entrypoint python api \
      tools/surveys/archive_interrupt_live.py "$boundary" || status=$?
    [ "$status" -eq 73 ]
    status=0
    archive_fetch || status=$?
    [ "$status" -eq 1 ] && [ ! -e "$proof/fetched-checkpoint.json" ]
    archive_publish
  done
  # No local exported checkpoint may supply the subsequent restore by accident.
  rm "$proof/recovery-checkpoint.json"
  else
    [ ! -e "$proof/recovery-checkpoint.json" ]
  fi
else
  source_compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/recovery.py export \
    --output /proof/recovery-checkpoint.json
fi
# Source DB, object volume and containers are gone before either target restore.
# Recovery material survives as a separate file or archive volume. Continuous
# coverage across loss of this host is deliberately not claimed by this test.
source_compose down --volumes --remove-orphans
verify_project_absent "$source_project"
if [ "$mode" != manual ]; then
  archive_fetch
  mv "$proof/fetched-checkpoint.json" "$proof/recovery-checkpoint.json"
fi
if [ "$mode" = durable ]; then
  python3 "$root/tools/surveys/network_override.py" "$proof/target.yml" "$archive_volume"
else
  python3 "$root/tools/surveys/network_override.py" "$proof/target.yml"
fi
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
verify_project_absent "$target_project"
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
verify_project_absent "$target_project"
mkdir -p "$root/.artifacts/surveys-restic"
python3 - "$proof/restic-recovery-proof.json" "$mode" <<'PY'
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
if sys.argv[2] == 'archive':
    result.update({
        'independentArchiveVolumeOutsideSourceProject': True,
        'staleArchiveRejectedBeforeOutput': True,
        'publisherAbruptExitBoundariesProven': ['after-pending', 'after-current'],
        'interruptedPublicationBlocksFetchUntilRepublished': True,
        'offlineArchiveFetchAfterSourceContainersAndVolumesRemoved': True,
    })
if sys.argv[2] == 'durable':
    result.update(json.loads((path.parent / 'durable-ack-proof.json').read_text()))
    result['offlineFetchedCheckpointMode600'] = result.pop('cliCheckpointExportMode600')
    result['independentArchiveVolumeOutsideSourceProject'] = True
    result['offlineArchiveFetchAfterSourceContainersAndVolumesRemoved'] = True
    result['limitations'] = [
        'Independent named volume models retained storage; physical remote-host durability is not covered',
        'This proves the exact acknowledged ledger; trustworthy unexpected-host-loss cutoff and pilot release-wrapper compatibility remain open',
    ]
path.write_text(json.dumps(result, indent=2) + '\n')
PY
cp "$proof/restic-recovery-proof.json" "$root/.artifacts/surveys-restic/"
if [ "$mode" != manual ]; then
  docker volume rm "$archive_volume" >/dev/null
  [ -z "$(docker volume ls -q --filter "name=^${archive_volume}$")" ]
  archive_owned=false
fi
echo "PASS: real encrypted Restic backup/rotation/check, source removal, fresh-target rejection and no-build recovery: $suffix"
