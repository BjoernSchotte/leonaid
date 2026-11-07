#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"
. "$root/tools/security/pulled-images.sh"

# The vulnerability gate (advisory downloads, own image build, 21 scans) is
# mostly network and image I/O; it runs beside the policy checks and the
# security stack test instead of after them. Both lanes must pass. Images it
# pulls stay until the job ends, because the test stack may use them too.
scan_log=$(mktemp)
scan_status=$(mktemp)
(
  status=0
  LEONAID_SCAN_KEEP_PULLED=1 /bin/sh "$root/tools/security/vulnerability-scan.sh" \
    >"$scan_log" 2>&1 || status=$?
  echo "$status" >"$scan_status"
) &
scan_pid=$!
finish_scan() {
  wait "$scan_pid" || true
  echo "ci-security: ---- vulnerability gate log ----"
  cat "$scan_log"
  echo "ci-security: ---- end of vulnerability gate log ----"
  result=$(cat "$scan_status")
  rm -f "$scan_log" "$scan_status"
  return "${result:-1}"
}
on_exit() {
  status=$?
  if [ -n "${scan_pid:-}" ] && kill -0 "$scan_pid" 2>/dev/null; then
    kill "$scan_pid" 2>/dev/null || true
    finish_scan || true
  fi
  exit "$status"
}
trap on_exit EXIT HUP INT TERM

python3 "$root/tools/local_tests_test.py"
python3 "$root/tools/testing/ci_fixture_test.py"
python3 "$root/tools/testing/image_tags_test.py"
python3 "$root/tools/testing/phase_test.py"

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
# The browser image is only needed by the pilot and release tests; free its
# ~2.7 GB for the image gates below unless it was already present before
# this run (see pulled-images.sh).
playwright_pulled=false
if pinned_image_absent "$PLAYWRIGHT_IMAGE"; then
  playwright_pulled=true
fi
/bin/sh "$root/tools/pilot/test.sh" "$root"
docker run --rm --network none \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  --volume "$root:/workspace:ro" \
  "$PLAYWRIGHT_IMAGE" \
  python3 /workspace/tools/release/release_test.py
if [ "$playwright_pulled" = true ]; then
  remove_pulled_image "$PLAYWRIGHT_IMAGE"
fi
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

python3 "$root/tools/testing/shared_stack.py" core tools/security/test.sh

if ! finish_scan; then
  scan_pid=""
  echo "ci-security: ERROR: vulnerability gate failed (log above)" >&2
  exit 1
fi
scan_pid=""

echo "ci-security: OK: policies, secrets, dependency audit and HIGH/CRITICAL image gates"
