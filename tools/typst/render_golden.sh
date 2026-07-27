#!/bin/sh
set -eu

root=${1:?Repository-Pfad fehlt}
output=${2:?Ausgabepfad fehlt}
image=${3:?Core-Image fehlt}

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
  /output
