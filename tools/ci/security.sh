#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"

python3 "$root/tools/local_tests_test.py"
python3 "$root/tools/testing/ci_fixture_test.py"
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

/bin/sh "$root/tools/security/vulnerability-scan.sh"

python3 "$root/tools/testing/shared_stack.py" core tools/security/test.sh

echo "ci-security: OK: policies, secrets, dependency audit and HIGH/CRITICAL image gates"
