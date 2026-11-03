#!/bin/sh
# Exercise the actual production image; compilation cannot detect ESM resolution failures.
set -eu
image=${1:?production public image required}
docker run --rm --network none --entrypoint sh "$image" -ec '
  node ./dist/server/entry.mjs &
  server=$!
  trap "kill $server 2>/dev/null || true; wait $server 2>/dev/null || true" EXIT
  attempt=0
  while [ "$attempt" -lt 30 ]; do
    if ! kill -0 "$server" 2>/dev/null; then
      wait "$server"
      exit 1
    fi
    if [ "$(wget -T 1 -qO- http://127.0.0.1:3000/health/ready || true)" = ready ]; then
      echo "public-runtime: OK: production Node server responds ready"
      exit 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  echo "public-runtime: ERROR: production server did not become ready" >&2
  exit 1
'

# Image transforms under the public service's runtime limits
# (infra/compose/compose.yml: mem_limit, cpus, pids_limit, read_only, cap_drop).
# libvips sizes its thread pool from the host CPU count; without the image's
# VIPS_CONCURRENCY=1 a many-core host exhausts pids_limit, images degrade to
# unoptimized and Node can die with SIGSEGV. CI runners have few cores, so the
# configured concurrency is asserted directly as well.
concurrency=$(docker run --rm --network none "$image" \
  node -e 'process.stdout.write(String(require("sharp").concurrency()))')
if [ "$concurrency" != 1 ]; then
  echo "public-runtime: ERROR: sharp concurrency is $concurrency, expected 1 (VIPS_CONCURRENCY)" >&2
  exit 1
fi
server="public-runtime-$$-$(date +%s)"
cleanup() { docker rm -f "$server" >/dev/null 2>&1 || true; }
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
docker run --detach --name "$server" --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --tmpfs /tmp:rw,nosuid,nodev,size=16m \
  --memory 128m --cpus 1 --pids-limit 64 "$image" >/dev/null
# The client shares the server's network namespace but has its own process and
# PID budget, so the requests do not consume the server's pids_limit.
client_status=0
docker run --rm --network "container:$server" --entrypoint node "$image" \
  --input-type=module -e '
  import { readdirSync } from "node:fs";
  const base = "http://127.0.0.1:3000";
  for (let attempt = 0; ; attempt++) {
    try { if ((await (await fetch(`${base}/health/ready`)).text()) === "ready") break; } catch {}
    if (attempt >= 30) throw new Error("public server did not become ready");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  const assets = readdirSync("/app/dist/client/_astro").filter((name) => /\.(png|jpe?g|webp)$/.test(name));
  if (assets.length === 0) throw new Error("no raster assets in the public build");
  const rounds = 10, parallel = 8, failures = [];
  for (let round = 0; round < rounds; round++) {
    await Promise.all(Array.from({ length: parallel }, async (_, index) => {
      const asset = assets[index % assets.length];
      const width = 200 + round * parallel + index;
      try {
        const response = await fetch(`${base}/_image?href=%2F_astro%2F${asset}&w=${width}&f=webp`);
        const body = new Uint8Array(await response.arrayBuffer());
        const webp = new TextDecoder().decode(body.subarray(8, 12)) === "WEBP";
        if (!response.ok || !webp) failures.push(`${asset}@${width}: HTTP ${response.status}, webp=${webp}`);
      } catch (error) {
        failures.push(`${asset}@${width}: ${error.cause?.code ?? error.message}`);
      }
    }));
  }
  if (failures.length) {
    console.error(`public-runtime: ${failures.length} image transforms failed:\n${failures.slice(0, 10).join("\n")}`);
    process.exit(1);
  }
  console.log(`public-runtime: ${rounds * parallel} concurrent WebP transforms of ${assets.length} assets succeeded`);
' || client_status=$?
state=$(docker inspect --format '{{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}}' "$server")
if [ "$state" != "true 0 false" ]; then
  echo "public-runtime: ERROR: public server not running after image transforms (running exit oom: $state)" >&2
  docker logs --tail 20 "$server" >&2 || true
  exit 1
fi
if [ "$client_status" != 0 ]; then
  echo "public-runtime: ERROR: image transform client failed ($client_status)" >&2
  exit 1
fi
if docker logs "$server" 2>&1 | grep -q 'could not optimize image'; then
  echo "public-runtime: ERROR: public server fell back to unoptimized images" >&2
  docker logs --tail 20 "$server" >&2 || true
  exit 1
fi
echo "public-runtime: OK: concurrent image transforms within service limits; server alive"
