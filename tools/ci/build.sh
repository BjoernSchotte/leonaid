#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
artifact_directory=${LEONAID_CI_ARTIFACT_DIR:-"$root/.artifacts/ci/build"}
case "$artifact_directory" in
  /*) ;;
  *) artifact_directory="$root/$artifact_directory" ;;
esac
mkdir -p "$artifact_directory"

docker compose \
  --project-name leonaid-ci-build \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
  build
docker compose \
  --project-name leonaid-ci-build \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
  config --images | sort >"$artifact_directory/compose-images.txt"

echo "ci-build: OK: kanonische Compose-Anwendung gebaut"
