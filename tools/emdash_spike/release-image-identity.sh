#!/bin/sh
set -eu
root=$1
. "$root/infra/locks/images.env"
# Build only this checkout's campaign image; create no named project, ports or
# networks. Keep Docker's content-addressed image/cache for later release proof.
image_id=$(docker build --quiet --file "$root/infra/compose/Dockerfile.campaign-site" "$root")
case "$image_id" in sha256:*) ;; *) echo "cms-image: missing built identity" >&2; exit 1 ;; esac
read_identity() {
  docker run --rm --read-only --network none --cap-drop ALL \
    --security-opt no-new-privileges --entrypoint node "$image_id" \
    --input-type=module -e '
    import fs from "node:fs";
    const value=JSON.parse(fs.readFileSync("/app/cms-release-identity.json","utf8"));
    const mode=process.argv[1];
    if(mode==="schema") value.editorialSchemaVersion+=1;
    else if(mode==="source") value.sources[Object.keys(value.sources)[0]]="0".repeat(64);
    else if(mode==="extra") value.unreviewed=true;
    else if(mode!=="clean") process.exit(2);
    process.stdout.write(JSON.stringify(value));' "$1"
}
verify_identity() {
  docker run --rm -i --read-only --network none --cap-drop ALL \
    --security-opt no-new-privileges --volume "$root:/workspace:ro" \
    --workdir /workspace "$PYTHON_IMAGE" \
    python tools/pilot_release/cms_image_identity.py verify --root /workspace
}
identity=$(read_identity clean)
printf '%s' "$identity" | verify_identity
for mutation in schema source extra; do
  identity=$(read_identity "$mutation")
  if printf '%s' "$identity" | verify_identity >/dev/null 2>&1; then
    echo "cms-image: changed identity accepted" >&2
    exit 1
  else
    result=$?
    [ "$result" -eq 1 ] || exit "$result"
  fi
done
echo "cms-image: actual built runtime identity matches checkout; changed schema/source/extra metadata rejected; read-only, no network, no service activation"
