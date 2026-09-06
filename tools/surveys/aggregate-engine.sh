#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project="surveys-engine-$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
proof=$(mktemp -d)
network=false
container=false
cleanup() {
  status=$?
  if [ "$container" = true ]; then docker rm -f "$project" >/dev/null; fi
  if [ "$network" = true ]; then docker network rm "$project" >/dev/null; fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
if docker network inspect "$project" >/dev/null 2>&1; then exit 1; fi
[ -z "$(docker ps -aq --filter "name=^/$project$")" ] || exit 1
# Separate from the full fresh-image infrastructure build; use pinned installed modules.
docker run --rm --volume "$root:/workspace:ro" --volume "$proof:/proof" \
  --workdir /workspace "$BUN_IMAGE" bun -e '
    if (require("survey-core/package.json").version !== "3.0.3") throw new Error("unexpected SurveyJS version");
    const result = await Bun.build({entrypoints:["infra/compose/survey-validator.mjs"],target:"bun",outdir:"/proof"});
    if (!result.success) throw new Error("aggregate engine bundle failed");
  '
subnet=$(python3 "$root/tools/surveys/network_override.py" --single)
docker network create --internal --subnet "$subnet" "$project" >/dev/null
network=true
docker run --detach --name "$project" --network "$project" --network-alias survey-validator \
  --user bun --cap-drop ALL --security-opt no-new-privileges:true \
  --volume "$proof/survey-validator.js:/app/validator.mjs:ro" \
  "$BUN_IMAGE" bun /app/validator.mjs >/dev/null
container=true
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
check verify
docker stop "$project" >/dev/null
check unavailable
docker start "$project" >/dev/null
ready
check verify
mkdir -p "$root/.artifacts/surveys-engine"
cp "$proof/surveys-aggregates.json" "$root/.artifacts/surveys-engine/"
docker rm -f "$project" >/dev/null
container=false
docker network rm "$project" >/dev/null
network=false
echo "PASS: $project private aggregate engine, actual HTTP outage/restart, no host ports, teardown verified"
