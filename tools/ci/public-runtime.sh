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
