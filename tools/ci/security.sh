#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"

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
docker run --rm \
  --volume "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  /bin/sh /workspace/tools/pins/test.sh /workspace
docker run --rm \
  --volume "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/schema/check_migrations.py \
  /workspace/migrations/versions

if git -C "$root" ls-files | grep -E '(^|/)(\\.env\\.local|sessions?\\.env)$'; then
  echo "ci-security: ERROR: lokale Secrets oder Sitzungen sind versioniert" >&2
  exit 1
fi

echo "ci-security: OK: Pins, Migrationen, Secrets und No-Test-Double-Policy"
