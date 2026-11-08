#!/bin/sh
# The quick tools/ci self-tests for ./leonaid check-fast (a few seconds in one
# container). The full set runs in tools/dx/stdlib_checks.sh (./leonaid check).
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
check conflict-markers python "$w/tools/ci/conflict_markers.py" "$w"
check check-parity python "$w/tools/dx/check_parity_test.py" "$w"
for test in axe_helper base_path_literals conflict_markers core_oneoff_user gate \
  leak_check no_test_doubles refit_timings select_suites workflow_contract; do
  check "$test" python "$w/tools/ci/${test}_test.py" "$w"
done
if [ -n "$failed" ]; then
  echo "fast-ci-checks: FAILED:$failed" >&2
  exit 1
fi
echo "fast-ci-checks: OK"
