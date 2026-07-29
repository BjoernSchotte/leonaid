#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
artifact_directory="$root/.artifacts/pilot043"

rm -rf "$artifact_directory"
mkdir -p "$artifact_directory"

docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_release/contract_test.py

LEONAID_UPGRADE_ARTIFACT_DIR="$artifact_directory" \
  /bin/sh "$root/tools/upgrade/test.sh" "$root"

docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_release/verify_artifacts.py \
    /workspace /workspace/.artifacts/pilot043

echo "pilot-release-test: OK: zwei reale Releaseversionen, identische Promotion,"
echo "pilot-release-test:     vollständige Golden Journeys, Migrationsfehler,"
echo "pilot-release-test:     Recovery und Rollback bewiesen"
