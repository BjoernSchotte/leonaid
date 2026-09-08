#!/bin/sh
set -eu

root=${1:?repository root required}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
/bin/sh "$root/tools/proxy/export-image.sh" "$root" "$tmp/proxy.tar"
docker run --rm --interactive \
  --volume leonaid-trivy-cache:/root/.cache/trivy \
  --entrypoint sh "$TRIVY_IMAGE" -eu -c \
  'cat > /tmp/proxy.tar; exec trivy "$@"' sh image \
  --input /tmp/proxy.tar \
  --scanners vuln --severity CRITICAL --ignore-unfixed --exit-code 1 \
  < "$tmp/proxy.tar"
