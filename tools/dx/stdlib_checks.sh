#!/bin/sh
# Stdlib-only repository checks of ./leonaid check in one container instead of
# one container per check. Runs every check, labels each result, fails if any
# failed. Runs in $PYTHON_IMAGE with the checkout mounted read-only at $1.
set -u
w=${1:-/workspace}
failed=
check() {
  label=$1
  shift
  echo "-- $label"
  if ! "$@"; then
    failed="$failed $label"
  fi
}
check pilot-contract python "$w/tools/pilot_contract/test.py" "$w"
check pilot-decisions python "$w/tools/pilot_decisions/test.py" "$w"
check pins /bin/sh "$w/tools/pins/test.sh" "$w"
check vuln-policy-test env PYTHONPATH="$w" python "$w/tools/security/vuln_policy_test.py"
check vuln-policy python "$w/tools/security/vuln_policy.py" check "$w"
check golden /bin/sh "$w/tools/golden/test.sh" "$w"
check no-test-doubles python "$w/tools/ci/no_test_doubles_test.py" "$w"
check workflow-contract python "$w/tools/ci/workflow_contract_test.py" "$w"
check select-suites python "$w/tools/ci/select_suites_test.py" "$w"
check gate python "$w/tools/ci/gate_test.py"
check post-merge python "$w/tools/ci/post_merge_test.py"
check sanitize-artifacts python "$w/tools/ci/sanitize_artifacts_test.py" "$w"
check conflict-markers-test python "$w/tools/ci/conflict_markers_test.py"
check conflict-markers python "$w/tools/ci/conflict_markers.py" "$w"
check axe-helper-test python "$w/tools/ci/axe_helper_test.py"
check axe-helper python "$w/tools/ci/axe_helper.py" "$w"
# Leitsystem only: no Hugeicons, Base UI or old token aliases.
check legacy-ui-test python "$w/tools/ci/legacy_ui_test.py"
check legacy-ui python "$w/tools/ci/legacy_ui.py" "$w"
check core-oneoff-user python "$w/tools/ci/core_oneoff_user.py" "$w"
check core-oneoff-user-test python "$w/tools/ci/core_oneoff_user_test.py" "$w"
check compose-overlays python "$w/tools/backup/compose_overlays_test.py"
check cms-bootstrap-state python "$w/tools/backup/cms_bootstrap_state_test.py"
check survey-restore-receipts python "$w/tools/backup/restore_state_test.py"
check systemd python "$w/tools/pilot_install/systemd_test.py" "$w"
check production-secrets env PYTHONPATH="$w" python "$w/tools/pilot_install/production_secrets_test.py" "$w"
check handoff python "$w/tools/handoff/check.py" "$w"
check fast-plan python "$w/tools/dx/fast_plan_test.py" "$w"
# The same tools/ci self-tests as CI (lint-types.sh, security.sh);
# tools/dx/check_parity_test.py keeps the lists in step.
check capture-command python "$w/tools/ci/capture_command_test.py" "$w"
check leak-check python "$w/tools/ci/leak_check_test.py"
check base-path-literals-test python "$w/tools/ci/base_path_literals_test.py"
check base-path-literals python "$w/tools/ci/base_path_literals.py" "$w"
check migrations python "$w/tools/schema/check_migrations.py" "$w/migrations/versions"
check shared-stack env PYTHONPATH="$w" python "$w/tools/testing/shared_stack_test.py"
check parallel-stacks env PYTHONPATH="$w" python "$w/tools/testing/parallel_stacks_test.py"
check check-parity python "$w/tools/dx/check_parity_test.py" "$w"
if [ -n "$failed" ]; then
  echo "stdlib-checks: FAILED:$failed" >&2
  exit 1
fi
echo "stdlib-checks: OK"
