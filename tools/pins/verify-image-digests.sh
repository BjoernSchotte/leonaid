#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)

# Every pinned image of the canonical lock, so no new pin can escape the check.
images=$(sed -n 's/^[A-Z][A-Z0-9_]*_IMAGE=//p' "$root/infra/locks/images.env")
if [ -z "$images" ]; then
  echo "image-digest: ERROR: no images found in infra/locks/images.env" >&2
  exit 1
fi

count=0
for image in $images; do
  tagged=${image%@*}
  expected=${image##*@}
  actual=$(docker buildx imagetools inspect "$tagged" | awk '/^Digest:/ {print $2; exit}')
  if [ "$actual" != "$expected" ]; then
    echo "image-digest: ERROR: $tagged expected $expected, registry has $actual" >&2
    exit 1
  fi
  count=$((count + 1))
done

echo "image-digest: OK: $count version tags resolve to their recorded digests"
