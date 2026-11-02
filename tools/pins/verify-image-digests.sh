#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
env_file="$root/infra/locks/images.env"

# Every locked image is verified. images.env is generated from
# external-systems.lock and tools/pins/check.py enforces their parity, so a new
# lock entry cannot silently escape this registry check.
count=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    '' | '#'*) continue ;;
    *_IMAGE=*) ;;
    *)
      echo "image-digest: ERROR: unexpected line in $env_file: $line" >&2
      exit 1
      ;;
  esac
  image=${line#*=}
  tagged=${image%@*}
  expected=${image##*@}
  actual=$(docker buildx imagetools inspect "$tagged" | awk '/^Digest:/ {print $2; exit}')
  if [ "$actual" != "$expected" ]; then
    echo "image-digest: ERROR: $tagged expected $expected, registry has $actual" >&2
    exit 1
  fi
  count=$((count + 1))
done <"$env_file"

[ "$count" -gt 0 ] || {
  echo "image-digest: ERROR: no images found in $env_file" >&2
  exit 1
}
echo "image-digest: OK: $count version tags resolve to their recorded digests"
