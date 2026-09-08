#!/bin/sh
# Test-only helper for the existing synthetic backup/upgrade/pilot fixtures.
# Those fixtures perform no survey mutations after this capture. Production
# freshness must come from independently retained recovery state instead.
prepare_survey_recovery_fixture() {
  fixture_compose=$1
  fixture_directory=$2
  LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
  LEONAID_SURVEY_ERASURE_CHECKPOINT="$fixture_directory/erasure-checkpoint.json"
  "$fixture_compose" run --rm --no-deps \
    --volume "$root:/repo:ro" --volume "$fixture_directory:/proof" \
    --workdir /repo --entrypoint python api tools/surveys/recovery.py export \
    --output /proof/erasure-checkpoint.json
  export LEONAID_SURVEY_ERASURE_CHECKPOINT LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH
}
