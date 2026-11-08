#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"

# Policy self-tests and the secret scan: light, one container at a time.
policies() {
  python3 "$root/tools/local_tests_test.py"
  python3 "$root/tools/testing/ci_fixture_test.py"
  python3 "$root/tools/testing/image_tags_test.py"
  python3 "$root/tools/testing/phase_test.py"
  echo "security: survey-restore-receipts"
  python3 "$root/tools/backup/restore_state_test.py"
  # tools/ci/run-job.sh wraps every CI job (needs Docker for the sanitizer).
  python3 "$root/tools/ci/run_job_test.py"

  docker run --rm \
    --volume "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/testing/shared_stack_test.py

  docker run --rm \
    --volume "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/ci/capture_command_test.py /workspace

  docker run --rm \
    --volume "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/ci/no_test_doubles_test.py /workspace
  docker run --rm \
    --volume "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/ci/workflow_contract_test.py /workspace
  docker run --rm \
    --volume "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/ci/sanitize_artifacts_test.py /workspace
  # The pilot and release tests use the browser image; the security stack
  # test beside them may use it too, so it stays until the job ends.
  /bin/sh "$root/tools/pilot/test.sh" "$root"
  docker run --rm --network none \
    --user "$(id -u):$(id -g)" -e HOME=/tmp \
    --volume "$root:/workspace:ro" \
    "$PLAYWRIGHT_IMAGE" \
    python3 /workspace/tools/release/release_test.py
  docker run --rm \
    --volume "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    /bin/sh /workspace/tools/pins/test.sh /workspace
  docker run --rm --network none -e PYTHONPATH=/workspace \
    --volume "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/security/vuln_policy_test.py
  docker run --rm \
    --volume "$root:/workspace:ro" \
    "$PYTHON_IMAGE" \
    python /workspace/tools/schema/check_migrations.py \
    /workspace/migrations/versions

  if git -C "$root" ls-files | grep -E '(^|/)(\\.env\\.local|sessions?\\.env)$'; then
    echo "ci-security: ERROR: local secrets or sessions are tracked in git" >&2
    exit 1
  fi

  docker run --rm \
    --volume "$root:/workspace:ro" \
    --volume leonaid-trivy-cache:/root/.cache/trivy \
    "$TRIVY_IMAGE" \
    filesystem \
    --scanners secret \
    --exit-code 1 \
    --skip-dirs /workspace/.artifacts \
    --skip-dirs /workspace/.cache \
    --skip-dirs /workspace/.git \
    --skip-dirs /workspace/.local \
    --skip-dirs /workspace/node_modules \
    --skip-files /workspace/.env.local \
    /workspace
}

if [ "${1:-}" = --policies ]; then
  # The lane runs as its own process, so set -e stays in force: a shell
  # ignores it inside a function or subshell whose status a caller tests.
  policies
  echo "ci-security: OK: policy lane"
  exit 0
fi

# Two lanes on one runner, both must pass: the policy lane beside the
# security stack test. The HIGH/CRITICAL image gate runs in its own job
# (ci.yml "Vulnerability gate", tools/security/vulnerability-scan.sh).
policy_log=$(mktemp)
policy_status=$(mktemp)
policy_pid=""
finish_policies() {
  wait "$policy_pid" || true
  echo "ci-security: ---- policy lane log ----"
  cat "$policy_log"
  echo "ci-security: ---- end of policy lane log ----"
  result=$(cat "$policy_status")
  rm -f "$policy_log" "$policy_status"
  return "${result:-1}"
}
on_exit() {
  status=$?
  if [ -n "${policy_pid:-}" ] && kill -0 "$policy_pid" 2>/dev/null; then
    kill "$policy_pid" 2>/dev/null || true
    finish_policies || true
  fi
  exit "$status"
}
trap on_exit EXIT HUP INT TERM

(
  status=0
  /bin/sh "$root/tools/ci/security.sh" --policies >"$policy_log" 2>&1 || status=$?
  echo "$status" >"$policy_status"
) &
policy_pid=$!

stack_status=0
python3 "$root/tools/testing/shared_stack.py" core tools/security/test.sh || stack_status=$?

policies_failed=false
if ! finish_policies; then
  policies_failed=true
fi
policy_pid=""
if [ "$policies_failed" = true ]; then
  echo "ci-security: ERROR: policy lane failed (log above)" >&2
fi
if [ "$stack_status" -ne 0 ]; then
  echo "ci-security: ERROR: security stack test failed with exit code $stack_status" >&2
fi
if [ "$policies_failed" = true ] || [ "$stack_status" -ne 0 ]; then
  exit 1
fi

echo "ci-security: OK: policies, secrets, dependency policy and the security stack test"
