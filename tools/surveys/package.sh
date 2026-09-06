#!/bin/sh
set -eu
root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project="surveys-package-$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
proof=$(mktemp -d)
artifact="$root/.artifacts/surveys-package"
network=false
volume=false
container=false
cleanup() {
  status=$?
  mkdir -p "$artifact"
  cp "$proof"/*.png "$proof"/package-proof.json "$proof"/consumer.lock "$artifact/" 2>/dev/null || true
  if [ "$status" -ne 0 ]; then
    cp -R "$proof"/first "$proof"/second "$artifact/" 2>/dev/null || true
  fi
  if [ "$container" = true ]; then docker rm -f "$project" >/dev/null; fi
  if [ "$volume" = true ]; then docker volume rm "$project" >/dev/null; fi
  if [ "$network" = true ]; then docker network rm "$project" >/dev/null; fi
  docker image rm "$project" >/dev/null 2>&1 || true
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM
docker build --file "$root/apps/surveys-demo/Dockerfile" --tag "$project" "$root"
subnet=$(python3 "$root/tools/surveys/network_override.py" --single)
docker network create --internal --subnet "$subnet" "$project" >/dev/null
network=true
docker volume create "$project" >/dev/null
volume=true
docker run --detach --name "$project" --network "$project" --network-alias consumer \
  --volume "$project:/data" --cap-drop ALL --security-opt no-new-privileges:true "$project" >/dev/null
container=true
ready() {
  attempts=0
  until docker exec "$project" wget -qO- http://127.0.0.1:8080/health >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    [ "$attempts" -lt 30 ] || { echo 'Independent consumer failed to become ready' >&2; exit 1; }
    sleep 1
  done
}
browser() {
  docker run --rm --network "container:$project" --env HOME=/tmp --env CI=1 \
    --env LEONAID_E2E_ARTIFACT_DIR=/proof --volume "$root:/workspace:ro" \
    --volume "$proof:/proof" --workdir /workspace "$PLAYWRIGHT_IMAGE" \
    node_modules/.bin/playwright test tests/e2e/surveys-package.spec.mjs \
    --grep "$1" --browser=chromium --output="/proof/$2" --reporter=line
}
ready
docker cp "$project:/consumer/package-proof.json" "$proof/package-proof.json"
docker cp "$project:/consumer/bun.lock" "$proof/consumer.lock"
browser 'saves a multipage' first
docker restart "$project" >/dev/null
ready
browser 'restores after backend restart' second
docker rm -f "$project" >/dev/null
container=false
docker volume rm "$project" >/dev/null
volume=false
docker network rm "$project" >/dev/null
network=false
echo 'PASS: packed external consumer, real SQLite persistence across restart, host messages/theme, no host ports, teardown verified'
