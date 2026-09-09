#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
. "$root/tools/testing/phase.sh"
project="surveys-engine-$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
. "$root/tools/surveys/standalone_resources.sh"
standalone_absent
proof=$(mktemp -d)
network=false
container=false
volume=false
image=false
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  standalone_cleanup || status=1
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# Exercise the production image without provisioning unrelated application services.
image=true
phase survey-aggregate-build docker buildx build --load \
  --file "$root/infra/compose/Dockerfile.survey-validator" --tag "$project" "$root"
subnet=$(python3 "$root/tools/surveys/network_override.py" --single)
network=true
docker network create --internal --subnet "$subnet" "$project" >/dev/null
container=true
docker run --detach --name "$project" --network "$project" --network-alias survey-validator \
  --user bun --cap-drop ALL --security-opt no-new-privileges:true \
  "$project" >/dev/null
ready() {
  attempts=0
  until docker exec "$project" wget -qO- http://127.0.0.1:8080/health >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    [ "$attempts" -lt 30 ] || { echo 'Aggregate engine did not become ready' >&2; exit 1; }
    sleep 1
  done
}
check() {
  docker run --rm --network "$project" --env PYTHONPATH=/workspace/src \
    --volume "$root:/workspace:ro" --volume "$proof:/proof" --workdir /workspace \
    "$UV_IMAGE" uv run --frozen --no-sync python tools/surveys/analysis_live.py "$1"
}
ready
phase survey-aggregate-verify check verify
docker stop "$project" >/dev/null
phase survey-aggregate-unavailable check unavailable
docker start "$project" >/dev/null
ready
phase survey-aggregate-restarted check verify
mkdir -p "$root/.artifacts/surveys-engine"
cp "$proof/surveys-aggregates.json" "$root/.artifacts/surveys-engine/"
docker rm -f "$project" >/dev/null
container=false
docker network rm "$project" >/dev/null
network=false
echo "PASS: $project private aggregate engine, actual HTTP outage/restart, no host ports, teardown verified"
