#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

images="$TWENTY_IMAGE
$POSTGRES_IMAGE
$REDIS_IMAGE
$RUSTFS_IMAGE
$SEAWEEDFS_IMAGE
$MAILPIT_IMAGE
$CADDY_IMAGE
$PYTHON_IMAGE
$UV_IMAGE
$NODE_IMAGE
$BUN_IMAGE
$TYPST_IMAGE
$PLAYWRIGHT_IMAGE
$SYFT_IMAGE
$TRIVY_IMAGE
$ALPINE_IMAGE
$LISTMONK_IMAGE
$OTEL_IMAGE"

count=0
old_ifs=$IFS
IFS='
'
for image in $images; do
  IFS=$old_ifs
  tagged=${image%@*}
  expected=${image##*@}
  actual=$(docker buildx imagetools inspect "$tagged" | awk '/^Digest:/ {print $2; exit}')
  if [ "$actual" != "$expected" ]; then
    echo "image-digest: ERROR: $tagged expected $expected, registry has $actual" >&2
    exit 1
  fi
  count=$((count + 1))
  IFS='
'
done
IFS=$old_ifs

echo "image-digest: OK: $count version tags resolve to their recorded digests"
