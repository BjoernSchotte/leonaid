#!/bin/sh
set -eu

root=${1:-$(pwd)}
mode=${2:-}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

if [ "$mode" != "--synthetic" ]; then
  echo "pilot-rehearsal-test: BLOCKED: Die produktionsnahe Generalprobe benötigt" >&2
  echo "pilot-rehearsal-test: reale Provider, DNS/TLS, privaten Import sowie" >&2
  echo "pilot-rehearsal-test: Fach- und Betreiberfreigaben. Für den lokalen" >&2
  echo "pilot-rehearsal-test: Echtdienstnachweis explizit --synthetic verwenden." >&2
  exit 78
fi

artifact_directory=${LEONAID_PILOT_REHEARSAL_ARTIFACT_DIR:-"$root/.artifacts/pilot050-synthetic"}
case "$artifact_directory" in
  /*) ;;
  *) artifact_directory="$root/$artifact_directory" ;;
esac
case "$artifact_directory" in
  "$root"/.artifacts/*) ;;
  *)
    echo "pilot-rehearsal-test: ERROR: Evidence-Pfad muss unter .artifacts/ liegen" >&2
    exit 64
    ;;
esac
summary="$artifact_directory/summary.json"
started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
release_commit=$(git -C "$root" rev-parse HEAD)
completed_steps=
current_step=user-admin
summary_written=false

projects="
leonaid-pilot050-identity
leonaid-pilot050-invitations
leonaid-pilot050-sessions
leonaid-pilot050-import
leonaid-pilot050-mail
leonaid-pilot050-runtime
leonaid-poc112-pilot050
leonaid-restore-pilot050
leonaid-pilot050-backup-s3
leonaid-pilot050-alerting
leonaid-pilot050-legal
leonaid-poc113-pilot050
leonaid-restore-poc113-pilot050
"

cleanup_project() {
  project=$1
  for container in $(docker ps --all --quiet \
    --filter "label=com.docker.compose.project=$project"); do
    docker rm --force "$container" >/dev/null 2>&1 || true
  done
  for network in $(docker network ls --quiet \
    --filter "label=com.docker.compose.project=$project"); do
    docker network rm "$network" >/dev/null 2>&1 || true
  done
  for volume in $(docker volume ls --quiet \
    --filter "label=com.docker.compose.project=$project"); do
    docker volume rm "$volume" >/dev/null 2>&1 || true
  done
}

cleanup_all() {
  for project in $projects; do
    cleanup_project "$project"
  done
}

write_summary() {
  evidence_status=$1
  evidence_failed_step=$2
  finished_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  failed_arguments=
  if [ -n "$evidence_failed_step" ]; then
    failed_arguments="--failed-step $evidence_failed_step"
  fi
  # shellcheck disable=SC2086
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    --env PYTHONPATH=/workspace \
    --volume "$root:/workspace:ro" \
    --volume "$artifact_directory:/proof" \
    --workdir /workspace \
    "$PYTHON_IMAGE" \
    python tools/pilot_rehearsal/contract.py write \
      --output /proof/summary.json \
      --status "$evidence_status" \
      --release-commit "$release_commit" \
      --started-at "$started_at" \
      --finished-at "$finished_at" \
      --completed "$completed_steps" \
      $failed_arguments
}

finalize() {
  exit_status=$?
  trap - EXIT HUP INT TERM
  cleanup_all
  if [ "$exit_status" -eq 0 ]; then
    if [ "$summary_written" != "true" ]; then
      write_summary passed ""
    fi
  else
    rm -f "$summary"
    write_summary failed "$current_step" || true
  fi
  exit "$exit_status"
}
trap finalize EXIT HUP INT TERM

assert_clean() {
  for project in $projects; do
    if docker ps --all --quiet \
      --filter "label=com.docker.compose.project=$project" | grep -q .; then
      echo "pilot-rehearsal-test: ERROR: Container-Reste für $project" >&2
      return 1
    fi
    if docker network ls --quiet \
      --filter "label=com.docker.compose.project=$project" | grep -q .; then
      echo "pilot-rehearsal-test: ERROR: Netzwerk-Reste für $project" >&2
      return 1
    fi
    if docker volume ls --quiet \
      --filter "label=com.docker.compose.project=$project" | grep -q .; then
      echo "pilot-rehearsal-test: ERROR: Volume-Reste für $project" >&2
      return 1
    fi
  done
}

run_step() {
  current_step=$1
  shift
  echo "pilot-rehearsal-test: START: $current_step"
  "$@"
  if [ -n "$completed_steps" ]; then
    completed_steps="$completed_steps,$current_step"
  else
    completed_steps=$current_step
  fi
  assert_clean
  echo "pilot-rehearsal-test: OK: $current_step"
}

rm -rf "$artifact_directory"
mkdir -p "$artifact_directory"
cleanup_all
assert_clean

docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_rehearsal/contract_test.py /workspace

run_step user-admin \
  env \
    LEONAID_IDENTITY_TEST_PROJECT=leonaid-pilot050-identity \
    LEONAID_INVITATION_TEST_PROJECT=leonaid-pilot050-invitations \
    LEONAID_SESSION_TEST_PROJECT=leonaid-pilot050-sessions \
    /bin/sh "$root/tools/user_admin/test.sh" "$root"

run_step crm-import-golden \
  env LEONAID_CRM_IMPORT_TEST_PROJECT=leonaid-pilot050-import \
    /bin/sh "$root/tools/twenty/import_test.sh" "$root"

run_step mail-relay \
  env LEONAID_MAIL_RELAY_TEST_PROJECT=leonaid-pilot050-mail \
    /bin/sh "$root/tools/mail_relay/test.sh" "$root"

run_step pilot-deployment \
  env \
    LEONAID_PILOT_RUNTIME_PROJECT=leonaid-pilot050-runtime \
    LEONAID_PILOT_BUILD_PROJECT=leonaid-pilot050-release-images \
    /bin/sh "$root/tools/pilot_deployment/test.sh" "$root"

run_step pilot-backup \
  env \
    LEONAID_BACKUP_TEST_SOURCE_PROJECT=leonaid-poc112-pilot050 \
    LEONAID_BACKUP_TEST_TARGET_PROJECT=leonaid-restore-pilot050 \
    LEONAID_PILOT_BACKUP_PROJECT=leonaid-pilot050-backup-s3 \
    /bin/sh "$root/tools/pilot_rehearsal/backup_test.sh" "$root"

run_step pilot-alerting \
  env LEONAID_PILOT_ALERTING_PROJECT=leonaid-pilot050-alerting \
    /bin/sh "$root/tools/pilot_alerting/test.sh" "$root"

run_step pilot-legal-config \
  env LEONAID_LEGAL_TEST_PROJECT=leonaid-pilot050-legal \
    /bin/sh "$root/tools/legal_configuration/test.sh" "$root"

run_step pilot-release \
  env \
    LEONAID_UPGRADE_TEST_PROJECT=leonaid-poc113-pilot050 \
    LEONAID_UPGRADE_ROLLBACK_PROJECT=leonaid-restore-poc113-pilot050 \
    /bin/sh "$root/tools/pilot_release/test.sh" "$root"

current_step=evidence
write_summary passed ""

docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$artifact_directory:/proof" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_rehearsal/contract.py verify /proof/summary.json

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$root:/workspace:ro" \
  --volume "$artifact_directory:/proof" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/ci/sanitize_artifacts.py \
    /proof /workspace/.env.local

summary_written=true
current_step=
echo "pilot-rehearsal-test: OK: vollständige synthetische Krapfentaxi-Generalprobe"
echo "pilot-rehearsal-test:     auf realen Diensten, leerem Zustand und drei Browsern"
