#!/bin/sh
# One CycloneDX SBOM of a pinned runtime image, straight from its registry.
# Usage: registry-scan.sh WORKDIR OUTPUT ID IMAGE
# Started four at a time by tools/sbom/generate.sh; every scan has its own
# temporary and cache directory under WORKDIR, its log in WORKDIR/ID.log.
set -eu
workdir=${1:?work directory required}
output=${2:?output directory required}
id=${3:?SBOM id required}
image=${4:?image reference required}
root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"
mkdir -p "$workdir/$id"
if ! docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e SYFT_CACHE_DIR=/tmp/syft-cache \
  -v "$workdir/$id:/tmp" \
  -v "$output:/out" \
  "$SYFT_IMAGE" \
  "registry:$image" -o "cyclonedx-json=/out/container-$id.cdx.json" \
  >"$workdir/$id.log" 2>&1; then
  echo "sbom: ERROR: registry SBOM $id failed:" >&2
  cat "$workdir/$id.log" >&2
  exit 1
fi
