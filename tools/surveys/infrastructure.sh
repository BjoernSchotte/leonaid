#!/bin/sh
set -eu
root=${1:-$(pwd)}
mode=${2:-infrastructure}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
# A fresh project per invocation; no published host ports and no shared volumes.
project="leonaid-surveys-$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
proof=$(mktemp -d)
artifact="$root/.artifacts/surveys-infrastructure"
owned=false
python3 "$root/tools/surveys/network_override.py" "$proof/compose.yml"
compose() {
  docker compose --project-name "$project" --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" --file "$proof/compose.yml" \
    --profile dev-mail "$@"
}
cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    compose ps >&2 || true
    # Keep raw traces local; never copy credentials or unrestricted logs into proofs.
    mkdir -p "$artifact"
    cp -R "$proof/test-results" "$artifact/" 2>/dev/null || true
    cp "$proof"/surveys-accessibility* "$artifact/" 2>/dev/null || true
  fi
  if [ "$owned" = true ]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
[ -f "$root/.env.local" ] || { echo 'Run ./leonaid bootstrap first' >&2; exit 1; }
# Refuse to touch any project that already has resources, even on PID reuse.
[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ] || exit 1
[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] || exit 1
owned=true
compose up --build --detach --wait --wait-timeout 420 proxy worker mailpit
compose run --rm --no-deps --volume "$root:/repo:ro" --workdir /repo \
  --entrypoint alembic api upgrade head
compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
  --workdir /repo --entrypoint python api tools/surveys/infrastructure.py
if [ "$mode" = responses ] || [ "$mode" = runner ] || [ "$mode" = lifecycle ]; then
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/responses.py
fi
if [ "$mode" = lifecycle ]; then
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/schedule.py prepare
  compose up --detach --wait --wait-timeout 60 worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/schedule.py recover
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/lifecycle.py
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/module.py seed
fi
if [ "$mode" = runner ]; then
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/timeouts.py prepare
  compose up --detach --wait --wait-timeout 60 worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/timeouts.py recover
  validator_check() {
    compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
      --workdir /repo --entrypoint python api tools/surveys/validation_live.py "$1"
  }
  validator_check cases
  validator_check seed
  compose stop survey-validator
  validator_check unavailable
  compose up --detach --wait --wait-timeout 60 survey-validator
  validator_check recover
  validator_check seed
  compose pause survey-validator
  validator_check unavailable
  compose unpause survey-validator
  validator_check recover
fi
if [ "$mode" = invitations ]; then
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/invitations.py prepare
  compose stop mailpit
  compose up --detach --wait --wait-timeout 60 worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/invitations.py failure
  compose up --detach --wait --wait-timeout 60 mailpit
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/invitations.py recover
fi
browser_specs="tests/e2e/surveys-infrastructure.spec.mjs"
state_worker_pid=""
if [ "$mode" = deletion-ui ]; then
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/recovery_live.py seed
  docker run --rm --network "${project}_edge" --env-file "$proof/session.env" \
    --env HOME=/tmp --env CI=1 --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" --workdir /workspace "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test tests/e2e/surveys-deletion.spec.mjs \
    --grep 'trash and request' --browser=chromium --output=/proof/test-results --reporter=line
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/deletion_ui_live.py
  docker run --rm --network "${project}_edge" --env-file "$proof/session.env" \
    --env HOME=/tmp --env CI=1 --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" --workdir /workspace "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test tests/e2e/surveys-deletion.spec.mjs \
    --grep 'failed deletion' --browser=chromium --output=/proof/test-results --reporter=line
  compose up --detach --wait --wait-timeout 60 worker
  browser_specs="$browser_specs tests/e2e/surveys-deletion.spec.mjs"
fi
if [ "$mode" = recovery ]; then
  recovery_probe() {
    compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
      --workdir /repo --entrypoint python api tools/surveys/recovery_live.py "$1"
  }
  compose stop worker
  recovery_probe seed
  compose stop proxy public api worker rustfs
  compose exec -T core-postgres pg_dump --username leonaid --dbname leonaid \
    --format custom --no-owner --no-privileges > "$proof/recovery-core.dump"
  docker run --rm --volume "${project}_rustfs-data:/source:ro" --volume "$proof:/proof" \
    "$ALPINE_IMAGE" tar -C /source -cf /proof/recovery-rustfs.tar .
  compose up --detach --wait --wait-timeout 90 rustfs api public proxy
  recovery_probe delete
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/recovery.py export \
    --output /proof/recovery-checkpoint.json
  compose stop proxy public api worker rustfs
  compose exec -T core-postgres pg_restore --username leonaid --dbname leonaid \
    --clean --if-exists --exit-on-error --no-owner --no-privileges < "$proof/recovery-core.dump"
  # This volume belongs exclusively to the fresh, collision-checked test project.
  docker run --rm --volume "${project}_rustfs-data:/target" --volume "$proof:/proof:ro" \
    "$ALPINE_IMAGE" sh -c 'find /target -mindepth 1 -delete && tar -C /target -xf /proof/recovery-rustfs.tar'
  compose up --detach --no-deps --wait --wait-timeout 90 rustfs
  recovery_probe restored
  cutoff=$(cat "$proof/recovery-cutoff.txt")
  . "$root/tools/backup/survey-erasure-gate.sh"
  reapply() {
    LEONAID_SURVEY_ERASURE_CHECKPOINT="$1" \
      LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH="$2" apply_survey_erasure_gate
  }
  rejected_gate() {
    bad_status=0
    reapply "$1" "$2" || bad_status=$?
    [ "$bad_status" -eq 1 ] || { echo 'Expected recovery gate rejection' >&2; exit 1; }
    for service in api public proxy worker; do
      [ -z "$(compose ps --status running --quiet "$service")" ] || exit 1
    done
    recovery_probe restored
  }
  rejected_gate '' "$cutoff"
  rejected_gate "$proof/recovery-checkpoint.json" ''
  rejected_gate "$proof/recovery-tampered.json" "$cutoff"
  # A cutoff after the export rejects an authentic but insufficiently current file.
  rejected_gate "$proof/recovery-checkpoint.json" '2099-01-01T00:00:00+00:00'
  reapply "$proof/recovery-checkpoint.json" "$cutoff"
  reapply "$proof/recovery-checkpoint.json" "$cutoff"
  recovery_probe verify
  compose up --detach --wait --wait-timeout 90 api public proxy worker
  recovery_probe online
fi
if [ "$mode" = retention ]; then
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/retention_live.py prepare
  compose up --detach --wait --wait-timeout 60 worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/retention_live.py recover
  browser_specs="$browser_specs tests/e2e/surveys-retention.spec.mjs"
fi
if [ "$mode" = deletion-races ]; then
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/deletion_races_live.py
fi
if [ "$mode" = deletion ]; then
  compose stop worker
  deletion_probe() {
    compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
      --workdir /repo --entrypoint python api tools/surveys/deletion_live.py "$1"
  }
  deletion_probe prepare
  crash_status=0
  deletion_probe crash || crash_status=$?
  [ "$crash_status" -eq 73 ] || { echo 'Expected deletion probe exit 73' >&2; exit 1; }
  deletion_probe recover
fi
if [ "$mode" = export-states ]; then
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/export_browser_live.py seed
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/export_states_live.py &
  state_worker_pid=$!
  browser_specs="$browser_specs tests/e2e/surveys-export-states.spec.mjs"
fi
if [ "$mode" = export-permissions ]; then
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/export_permissions_live.py
fi
if [ "$mode" = export-recovery ]; then
  recovery() {
    compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
      --workdir /repo --entrypoint python api tools/surveys/export_recovery_live.py "$@"
  }
  compose stop worker
  recovery seed crash
  crash_status=0
  recovery crash || crash_status=$?
  [ "$crash_status" -eq 73 ] || { echo 'Expected export probe exit 73' >&2; exit 1; }
  recovery inspect-crash
  compose up --detach --wait --wait-timeout 60 worker
  recovery recover
  compose stop worker
  recovery seed cancel
  crash_status=0
  recovery crash || crash_status=$?
  [ "$crash_status" -eq 73 ] || { echo 'Expected export probe exit 73' >&2; exit 1; }
  recovery inspect-crash
  recovery cancel
  compose up --detach --wait --wait-timeout 60 worker
  recovery recover-cancel
  compose stop worker
  recovery seed renderer
  recovery renderer-fail
  recovery inspect-failure
  compose up --detach --wait --wait-timeout 60 worker
  recovery recover
  compose stop worker
  recovery seed storage
  compose stop rustfs
  compose up --detach --no-deps --wait --wait-timeout 60 worker
  recovery inspect-failure
  compose up --detach --wait --wait-timeout 60 rustfs
  recovery recover
fi
if [ "$mode" = exports ]; then
  browser_specs="$browser_specs tests/e2e/surveys-exports.spec.mjs"
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/exports_live.py prepare
  compose up --detach --wait --wait-timeout 60 worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/exports_live.py recover
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/export_browser_live.py seed
fi
if [ "$mode" = analysis ]; then
  browser_specs="$browser_specs tests/e2e/surveys-analytics.spec.mjs tests/e2e/surveys-responses.spec.mjs"
  compose stop worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/analysis_snapshot_live.py prepare
  compose up --detach --wait --wait-timeout 60 worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/analysis_snapshot_live.py recover
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/raw_responses_live.py
fi
if [ "$mode" = aggregates ]; then
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/analysis_live.py verify
  compose stop survey-validator
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/analysis_live.py unavailable
  compose up --detach --wait --wait-timeout 60 survey-validator
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/analysis_live.py verify
fi
if [ "$mode" = invitations ]; then
  browser_specs="$browser_specs tests/e2e/surveys-invitations.spec.mjs"
fi
if [ "$mode" = lifecycle ]; then
  browser_specs="$browser_specs tests/e2e/surveys-module.spec.mjs"
fi
if [ "$mode" = editor ]; then
  browser_specs="$browser_specs tests/e2e/surveys-editor.spec.mjs tests/e2e/surveys-authoring.spec.mjs tests/e2e/surveys-import-recovery.spec.mjs tests/e2e/surveys-accessibility.spec.mjs"
fi
if [ "$mode" = runner ]; then
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/browser_seed.py
  browser_specs="$browser_specs tests/e2e/surveys-runner.spec.mjs"
fi
docker run --rm --network "${project}_edge" --env-file "$proof/session.env" \
  --env HOME=/tmp --env CI=1 --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
  --env LEONAID_E2E_ARTIFACT_DIR=/proof --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" --workdir /workspace "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test $browser_specs \
  --grep-invert 'trash and request|failed deletion' \
  --browser=chromium --output=/proof/test-results --trace=retain-on-failure --reporter=line
mkdir -p "$artifact"
if [ "$mode" = lifecycle ]; then
  cp "$proof/lifecycle-proof.json" "$artifact/"
fi
if [ "$mode" = deletion-ui ]; then
  cp "$proof/deletion-ui-proof.json" "$artifact/"
  cp "$proof/deletion-confirm-mobile.png" "$artifact/"
  cp "$proof/deletion-completed-mobile.png" "$artifact/"
fi
if [ "$mode" = recovery ]; then
  cp "$proof/recovery-proof.json" "$artifact/"
fi
if [ "$mode" = retention ]; then
  cp "$proof/retention-proof.json" "$artifact/"
  cp "$proof/retention-browser-proof.json" "$artifact/"
  cp "$proof/retention-mobile.png" "$artifact/"
fi
if [ "$mode" = deletion-races ]; then
  cp "$proof/deletion-races-proof.json" "$artifact/"
fi
if [ "$mode" = deletion ]; then
  cp "$proof/deletion-proof.json" "$artifact/"
fi
if [ "$mode" = export-states ]; then
  wait "$state_worker_pid"
  cp "$proof/export-state-worker-proof.json" "$artifact/"
  cp "$proof/export-state-browser-proof.json" "$artifact/"
  cp "$proof/export-state-failed.png" "$artifact/"
fi
if [ "$mode" = export-permissions ]; then
  cp "$proof/export-permission-boundaries.json" "$artifact/"
fi
if [ "$mode" = export-recovery ]; then
  cp "$proof/export-recovery-proof.json" "$artifact/"
fi
if [ "$mode" = exports ]; then
  docker run --rm --network "${project}_edge" --env-file "$proof/session.env" \
    --env HOME=/tmp --env CI=1 --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" --workdir /workspace "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test tests/e2e/surveys-export-values.spec.mjs --grep 'populated snapshot|export-only members' \
    --browser=chromium --output=/proof/test-results --trace=retain-on-failure --reporter=line
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/export_browser_live.py verify-revoke
  docker run --rm --network "${project}_edge" --env-file "$proof/session.env" \
    --env HOME=/tmp --env CI=1 --env LEONAID_E2E_BASE_URL=https://proxy:8443 \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" --workdir /workspace "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test tests/e2e/surveys-export-values.spec.mjs --grep 'revoked report' \
    --browser=chromium --output=/proof/test-results --trace=retain-on-failure --reporter=line
  cp "$proof/export-only-proof.json" "$artifact/"
  cp "$proof/export-only-mobile.png" "$artifact/"
  cp "$proof/export-browser-values-proof.json" "$artifact/"
  cp "$proof/export-browser-permissions-proof.json" "$artifact/"
  cp "$proof/survey-exports-proof.json" "$artifact/"
  cp "$proof/survey-worker-report.pdf" "$artifact/"
  cp "$proof/survey-export-browser.json" "$artifact/"
  cp "$proof/surveys-exports-mobile.png" "$artifact/"
fi
if [ "$mode" = analysis ]; then
  cp "$proof/survey-analysis-snapshot.json" "$artifact/"
  cp "$proof/raw-response-proof.json" "$artifact/"
  cp "$proof"/surveys-responses-*.png "$artifact/"
  cp "$proof"/surveys-analytics-*.png "$artifact/"
fi
if [ "$mode" = aggregates ]; then
  cp "$proof/surveys-aggregates.json" "$artifact/"
fi
if [ "$mode" = invitations ]; then
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/invitations.py verify
fi
if [ "$mode" = lifecycle ]; then
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/module.py verify
  cp "$proof"/surveys-module-*.png "$artifact/"
fi
cp "$proof/surveys-public.png" "$artifact/"
if [ "$mode" = editor ]; then
  cp "$proof/surveys-editor.png" "$artifact/"
  cp "$proof"/surveys-authoring-*.png "$artifact/"
  cp "$proof"/surveys-accessibility* "$artifact/"
fi
if [ "$mode" = runner ]; then
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/recovery_verify.py
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/restart.py prepare
  compose restart api worker
  compose up --detach --no-deps --wait --wait-timeout 90 api worker
  compose run --rm --no-deps --volume "$root:/repo:ro" --volume "$proof:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/restart.py recover
  cp "$proof/surveys-mid-page.png" "$artifact/"
fi
compose down --volumes --remove-orphans
[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]
[ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ]
echo 'PASS: isolated survey foundation, real API/PostgreSQL/browser, no host ports, teardown verified'
