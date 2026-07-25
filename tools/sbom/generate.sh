#!/bin/sh
set -eu

root=${1:-$(pwd)}
output=${2:-"$root/.artifacts/sbom"}
root=$(cd "$root" && pwd)
mkdir -p "$output"
output=$(cd "$output" && pwd)
. "$root/infra/locks/images.env"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir -p "$tmp/python" "$tmp/frontend"

cp "$root/pyproject.toml" "$root/uv.lock" "$tmp/python/"
docker run --rm \
  -v "$tmp/python:/workspace" \
  -w /workspace \
  "$UV_IMAGE" \
  uv sync --frozen --no-dev --no-install-project

cp "$root/package.json" "$root/bun.lock" "$tmp/frontend/"
docker run --rm \
  -v "$tmp/frontend:/workspace" \
  -w /workspace \
  "$BUN_IMAGE" \
  bun install --frozen-lockfile --ignore-scripts

docker run --rm \
  -v "$tmp/python:/scan:ro" \
  -v "$output:/out" \
  "$SYFT_IMAGE" \
  dir:/scan -o cyclonedx-json=/out/python.cdx.json
docker run --rm \
  -v "$tmp/frontend:/scan:ro" \
  -v "$output:/out" \
  "$SYFT_IMAGE" \
  dir:/scan --select-catalogers +javascript-package-cataloger \
  -o cyclonedx-json=/out/frontend.cdx.json

python_image="$PYTHON_IMAGE"
node_image="$NODE_IMAGE"
twenty_image="$TWENTY_IMAGE"
postgres_image="$POSTGRES_IMAGE"
redis_image="$REDIS_IMAGE"
rustfs_image="$RUSTFS_IMAGE"
mailpit_image="$MAILPIT_IMAGE"
caddy_image="$CADDY_IMAGE"
typst_image="$TYPST_IMAGE"
playwright_image="$PLAYWRIGHT_IMAGE"
listmonk_image="$LISTMONK_IMAGE"
otel_image="$OTEL_IMAGE"

for system_id in python node twenty postgres redis rustfs mailpit caddy typst playwright listmonk otel; do
  eval "image=\${${system_id}_image}"
  docker run --rm \
    -v "$output:/out" \
    "$SYFT_IMAGE" \
    "registry:$image" -o "cyclonedx-json=/out/container-$system_id.cdx.json"
done

docker run --rm \
  -v "$output:/sbom:ro" \
  -v "$root/tools/sbom/verify.py:/verify.py:ro" \
  "$PYTHON_IMAGE" \
  python /verify.py /sbom

echo "sbom: OK: Python, frontend and 12 runtime container SBOMs in $output"
