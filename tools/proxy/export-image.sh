#!/bin/sh
set -eu

root=${1:?repository root required}
archive=${2:?output archive required}
root=$(cd "$root" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

# No shared image tag: export the exact result of the runtime Dockerfile.
docker buildx build --load --iidfile "$tmp/image-id" "$root/infra/proxy/image"
docker image save --output "$archive" "$(cat "$tmp/image-id")"
