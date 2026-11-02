#!/bin/sh
set -eu

root=${1:?repository path missing}
output=${2:?output path missing}
image=${3:?core image missing}
# Acceptance rendering remains unconditional unless a seed explicitly opts in.
reuse=${4:-}
set --
if [ "$reuse" = reuse ]; then
  image=$(docker image inspect --format '{{.Id}}' "$image")
  set -- --renderer-id "$image"
fi

root=$(cd "$root" && pwd)
mkdir -p "$output"
output=$(cd "$output" && pwd)

docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  --env PYTHONPATH=/workspace/src \
  --volume "$root:/repo:ro" \
  --volume "$output:/output" \
  --entrypoint python \
  "$image" \
  /repo/tools/typst/render_fixtures.py \
  /repo/tests/fixtures/golden/v1/documents \
  /output "$@"
