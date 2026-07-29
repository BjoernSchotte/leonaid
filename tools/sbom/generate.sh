#!/bin/sh
set -eu

root=${1:-$(pwd)}
output=${2:-"$root/.artifacts/sbom"}
root=$(cd "$root" && pwd)
mkdir -p "$output"
output=$(cd "$output" && pwd)
. "$root/infra/locks/images.env"
host_user_id=$(id -u)
host_group_id=$(id -g)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir -p "$tmp/python" "$tmp/frontend" "$tmp/syft-tmp"

cp "$root/pyproject.toml" "$root/uv.lock" "$tmp/python/"
docker run --rm \
  --user "$host_user_id:$host_group_id" \
  -e UV_CACHE_DIR=/tmp/uv-cache \
  -v "$tmp/python:/workspace" \
  -w /workspace \
  "$UV_IMAGE" \
  uv sync --frozen --no-dev --no-install-project

cp "$root/package.json" "$root/bun.lock" "$tmp/frontend/"
for workspace_dir in apps packages; do
  if [ -d "$root/$workspace_dir" ]; then
    cp -R "$root/$workspace_dir" "$tmp/frontend/$workspace_dir"
  fi
done
docker run --rm \
  --user "$host_user_id:$host_group_id" \
  -e BUN_INSTALL_CACHE_DIR=/tmp/bun-cache \
  -v "$tmp/frontend:/workspace" \
  -w /workspace \
  "$BUN_IMAGE" \
  bun install --frozen-lockfile --ignore-scripts

docker run --rm \
  --user "$host_user_id:$host_group_id" \
  -e SYFT_CACHE_DIR=/tmp/syft-cache \
  -v "$tmp/syft-tmp:/tmp" \
  -v "$tmp/python:/scan:ro" \
  -v "$output:/out" \
  "$SYFT_IMAGE" \
  dir:/scan -o cyclonedx-json=/out/python.cdx.json
docker run --rm \
  --user "$host_user_id:$host_group_id" \
  -e SYFT_CACHE_DIR=/tmp/syft-cache \
  -v "$tmp/syft-tmp:/tmp" \
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
seaweedfs_image="$SEAWEEDFS_IMAGE"
mailpit_image="$MAILPIT_IMAGE"
caddy_image="$CADDY_IMAGE"
typst_image="$TYPST_IMAGE"
playwright_image="$PLAYWRIGHT_IMAGE"
listmonk_image="$LISTMONK_IMAGE"
otel_image="$OTEL_IMAGE"

for system_id in python node twenty postgres redis rustfs seaweedfs mailpit caddy typst playwright listmonk otel prometheus alertmanager; do
  eval "image=\${${system_id}_image}"
  docker run --rm \
    --user "$host_user_id:$host_group_id" \
    -e SYFT_CACHE_DIR=/tmp/syft-cache \
    -v "$tmp/syft-tmp:/tmp" \
    -v "$output:/out" \
    "$SYFT_IMAGE" \
    "registry:$image" -o "cyclonedx-json=/out/container-$system_id.cdx.json"
done

docker run --rm \
  -v "$output:/sbom:ro" \
  -v "$root/tools/sbom/verify.py:/verify.py:ro" \
  "$PYTHON_IMAGE" \
  python /verify.py /sbom

echo "sbom: OK: Python, frontend and 13 runtime container SBOMs in $output"
