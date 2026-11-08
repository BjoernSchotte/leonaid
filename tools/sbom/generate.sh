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
registry_pid=""
cleanup() {
  if [ -n "$registry_pid" ]; then
    kill "$registry_pid" 2>/dev/null || true
    wait "$registry_pid" 2>/dev/null || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT HUP INT TERM
mkdir -p "$tmp/python" "$tmp/frontend" "$tmp/syft-tmp"

# The 14 pinned runtime images need nothing from the checkout. Their SBOMs
# come straight from the registries, four at a time, beside the Python,
# frontend and proxy SBOMs below (one after another they took 168 s with the
# rest, run 42505220242).
mkdir -p "$tmp/registry"
printf '%s %s\n' \
  python "$PYTHON_IMAGE" node "$NODE_IMAGE" twenty "$TWENTY_IMAGE" \
  postgres "$POSTGRES_IMAGE" valkey "$VALKEY_IMAGE" rustfs "$RUSTFS_IMAGE" \
  seaweedfs "$SEAWEEDFS_IMAGE" mailpit "$MAILPIT_IMAGE" typst "$TYPST_IMAGE" \
  playwright "$PLAYWRIGHT_IMAGE" listmonk "$LISTMONK_IMAGE" otel "$OTEL_IMAGE" \
  prometheus "$PROMETHEUS_IMAGE" alertmanager "$ALERTMANAGER_IMAGE" |
  xargs -n 2 -P 4 /bin/sh "$root/tools/sbom/registry-scan.sh" "$tmp/registry" "$output" &
registry_pid=$!

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

/bin/sh "$root/tools/proxy/export-image.sh" "$root" "$tmp/proxy.tar"
docker run --rm \
  --user "$host_user_id:$host_group_id" \
  -e SYFT_CACHE_DIR=/tmp/syft-cache \
  -v "$tmp/syft-tmp:/tmp" \
  -v "$tmp/proxy.tar:/image/proxy.tar:ro" \
  -v "$output:/out" \
  "$SYFT_IMAGE" \
  docker-archive:/image/proxy.tar -o cyclonedx-json=/out/container-caddy.cdx.json

if ! wait "$registry_pid"; then
  registry_pid=""
  echo "sbom: ERROR: a runtime image SBOM failed (log above)" >&2
  exit 1
fi
registry_pid=""

docker run --rm \
  -v "$output:/sbom:ro" \
  -v "$root/tools/sbom/verify.py:/verify.py:ro" \
  "$PYTHON_IMAGE" \
  python /verify.py /sbom

echo "sbom: OK: Python, frontend and 15 runtime container SBOMs in $output"
