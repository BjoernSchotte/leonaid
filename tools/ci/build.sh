#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
artifact_directory=${LEONAID_CI_ARTIFACT_DIR:-"$root/.artifacts/ci/build"}
case "$artifact_directory" in
  /*) ;;
  *) artifact_directory="$root/$artifact_directory" ;;
esac
mkdir -p "$artifact_directory"

compose() {
  docker compose \
    --project-name leonaid-ci-build \
    --env-file "$root/.env.local" \
    --file "$root/infra/compose/compose.yml" \
    "$@"
}

# Images whose content hash is already present (pulled from GHCR by the
# build-cache action, decision E-020) are only tagged; the rest is built.
config=$(mktemp)
trap 'rm -f "$config"' EXIT
compose config --format json >"$config"
missing=$(python3 -I "$root/tools/ci/prebuilt_images.py" adopt leonaid-ci-build "$config")
if [ -n "$missing" ]; then
  # One word per service.
  # shellcheck disable=SC2086
  compose build $missing
else
  echo "ci-build: every image reused by content hash; nothing to build"
fi
compose config --images | sort >"$artifact_directory/compose-images.txt"

/bin/sh "$root/tools/ci/public-runtime.sh" leonaid-ci-build-public
/bin/sh "$root/tools/ci/proxy-runtime.sh" leonaid-ci-build-proxy "$root/.env.local"

echo "ci-build: OK: kanonische Compose-Anwendung gebaut"
