#!/bin/sh
set -eu
root=$1
reference=$2
. "$root/infra/locks/images.env"
fail() { echo "cms-image-preflight: refused; CMS must remain stopped" >&2; exit 1; }
# Resolve once, then execute the immutable local ID. Do not pull or trust a
# mutable tag between inspection and metadata extraction.
image_id=$(docker image inspect --format '{{.Id}}' "$reference" 2>/dev/null) || fail
case "$image_id" in sha256:*) ;; *) fail ;; esac
digest=${image_id#sha256:}
[ "${#digest}" -eq 64 ] || fail
case "$digest" in *[!0-9a-f]*) fail ;; esac
identity=$(docker run --rm --read-only --network none --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint node "$image_id" \
  -e 'try { process.stdout.write(require("node:fs").readFileSync("/app/cms-release-identity.json","utf8")); } catch { process.exit(1); }' \
  2>/dev/null) || fail
if ! printf '%s' "$identity" | docker run --rm -i --read-only --network none \
  --cap-drop ALL --security-opt no-new-privileges \
  --volume "$root:/workspace:ro" --workdir /workspace "$PYTHON_IMAGE" \
  python tools/pilot_release/cms_image_identity.py verify --root /workspace >/dev/null 2>&1; then
  fail
fi
# The caller must use this exact ID for activation. No project data is mounted
# into either probe; neither process can reach a database or the public network.
printf '%s\n' "$image_id"
