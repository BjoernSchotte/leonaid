#!/bin/sh
# Run the proxy image under the proxy service's runtime limits and settings
# from infra/compose/compose.yml (pids_limit, cpus, mem_limit, init, caps,
# healthcheck) and drive it with concurrent file_server/encode load over HTTP
# and HTTPS plus repeated runs of the service's own healthcheck.
#
# Regression for the proxy pid exhaustion: the HTTPS healthcheck runs BusyBox
# wget, which forks an ssl_client helper and exits without waiting for it. The
# orphan is reparented to the container's PID 1. Caddy as PID 1 never reaps
# foreign children, so every healthcheck left a zombie; after a few minutes
# the zombies filled pids_limit and the Go runtime aborted with
# "fatal error: newosproc" at its next new OS thread. The service therefore
# runs with `init: true`. This check fails on any zombie, on a pids peak above
# half of pids_limit, and when Caddy dies.
#
# Usage: tools/ci/proxy-runtime.sh <proxy image> [env file]
set -eu
image=${1:?proxy image required}
root=$(cd "$(dirname "$0")/../.." && pwd)
env_file=${2:-"$root/.env.local"}
healthcheck_runs=${LEONAID_PROXY_RUNTIME_HEALTHCHECKS:-40}
load_rounds=${LEONAID_PROXY_RUNTIME_ROUNDS:-6}

fail() {
  echo "proxy-runtime: ERROR: $*" >&2
  exit 1
}

work=$(mktemp -d)
name="proxy-runtime-$$-$(date +%s)"
cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker network rm "$name" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

# The service definition is the source of truth; nothing here repeats a limit.
docker compose --project-name "$name" --env-file "$env_file" \
  --file "$root/infra/compose/compose.yml" config --format json >"$work/compose.json"
python3 - "$work/compose.json" "$work" <<'PY'
import json
import shlex
import sys
from pathlib import Path

proxy = json.loads(Path(sys.argv[1]).read_text())["services"]["proxy"]
work = Path(sys.argv[2])
for key in ("pids_limit", "cpus", "mem_limit"):
    if not proxy.get(key):
        sys.exit(f"proxy-runtime: ERROR: proxy service has no {key}")
args = [
    f"--pids-limit={proxy['pids_limit']}",
    f"--cpus={proxy['cpus']}",
    f"--memory={proxy['mem_limit']}",
]
if proxy.get("init"):
    args.append("--init")
args += [f"--cap-drop={cap}" for cap in proxy.get("cap_drop", [])]
args += [f"--cap-add={cap}" for cap in proxy.get("cap_add", [])]
args += [f"--security-opt={opt}" for opt in proxy.get("security_opt", [])]
args += [f"--env={key}={value}" for key, value in (proxy.get("environment") or {}).items()]
test = proxy["healthcheck"]["test"]
if test[0] == "CMD-SHELL":
    health = test[1]
elif test[0] == "CMD":
    health = shlex.join(test[1:])
else:
    sys.exit(f"proxy-runtime: ERROR: unsupported healthcheck {test!r}")
(work / "run-args").write_text("\n".join(args) + "\n")
(work / "healthcheck").write_text(health)
(work / "pids-limit").write_text(str(proxy["pids_limit"]))
PY
pids_limit=$(cat "$work/pids-limit")
healthcheck=$(cat "$work/healthcheck")

# A file_server/encode route like the dev gallery (.local/dev/caddy.d): large
# incompressible files (served with sendfile) and compressible text (zstd/gzip).
mkdir -p "$work/local.d" "$work/static"
cat >"$work/local.d/proxy-runtime.caddy" <<'CADDY'
handle_path /_proxy_runtime/* {
	root * /srv/local-static
	encode zstd gzip
	file_server
}
CADDY
i=0
while [ "$i" -lt 16 ]; do
  head -c 2097152 /dev/urandom >"$work/static/image-$i.bin"
  yes "LeonAid proxy runtime check line $i" | head -c 2097152 >"$work/static/text-$i.txt"
  i=$((i + 1))
done
chmod -R a+rX "$work"

# Healthcheck and client reach the proxy as `proxy` like the Compose network.
docker network create --internal "$name" >/dev/null
# shellcheck disable=SC2046 # one docker run argument per line
docker run --detach --name "$name" --network "$name" --network-alias proxy \
  $(cat "$work/run-args") \
  --volume "$root/infra/proxy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  --volume "$work/local.d:/etc/caddy/local.d:ro" \
  --volume "$work/static:/srv/local-static:ro" \
  "$image" >/dev/null

attempt=0
until docker exec "$name" sh -c "$healthcheck" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ] || [ "$(docker inspect --format '{{.State.Running}}' "$name")" != true ]; then
    docker logs --tail 20 "$name" >&2 || true
    fail "proxy did not become healthy"
  fi
  sleep 1
done

# The healthcheck runs inside the proxy container exactly as Docker runs it.
(
  run=0
  while [ "$run" -lt "$healthcheck_runs" ]; do
    docker exec "$name" sh -c "$healthcheck" >/dev/null 2>&1 || exit 1
    run=$((run + 1))
  done
) &
health_job=$!

# The client shares the proxy's network namespace but has its own pid budget.
client_status=0
docker run --rm --network "container:$name" --entrypoint sh "$image" -ec '
  rounds=$1
  # One curl per scheme: a single parallel curl mixing both schemes on one
  # host reuses TLS connections for plain HTTP URLs.
  for base in http://localhost:8080 https://localhost:8443; do
    list=/tmp/urls-${base%%:*}
    : >"$list"
    round=0
    while [ "$round" -lt "$rounds" ]; do
      for i in $(seq 0 15); do
        for file in image-$i.bin text-$i.txt; do
          printf "url = \"%s/_proxy_runtime/%s\"\noutput = \"/dev/null\"\n" "$base" "$file"
        done
      done >>"$list"
      round=$((round + 1))
    done
    curl --silent --insecure --parallel --parallel-max 32 \
      --header "Accept-Encoding: zstd, gzip" \
      --write-out "%{http_code} %{url} %{errormsg}\n" \
      --config "$list" >"$list.codes" 2>&1 &
  done
  wait
  total=$(cat /tmp/urls-http /tmp/urls-https | grep -c "^url")
  codes=$(cat /tmp/urls-http.codes /tmp/urls-https.codes)
  ok=$(printf "%s\n" "$codes" | grep -c "^200 " || true)
  if [ "$ok" != "$total" ]; then
    echo "proxy-runtime: $((total - ok)) of $total concurrent requests failed:" >&2
    printf "%s\n" "$codes" | grep -v "^200 " | head -5 >&2
    exit 1
  fi
  echo "proxy-runtime: $total concurrent file_server requests (HTTP and HTTPS) succeeded"
' proxy-runtime-client "$load_rounds" || client_status=$?

health_status=0
wait "$health_job" || health_status=$?

state=$(docker inspect --format '{{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}}' "$name")
if [ "$state" != "true 0 false" ]; then
  docker logs --tail 30 "$name" >&2 || true
  fail "proxy not running after load (running exit oom: $state)"
fi
# One exec reads every counter so that its own pid is counted once.
report=$(docker exec "$name" sh -c '
  cg=/sys/fs/cgroup
  zombies=0
  threads=0
  for status in /proc/[0-9]*/status; do
    case "$(sed -n "s/^State:[[:space:]]*\(.\).*/\1/p" "$status" 2>/dev/null)" in
      Z) zombies=$((zombies + 1)) ;;
    esac
    if [ "$(sed -n "s/^Name:[[:space:]]*//p" "$status" 2>/dev/null)" = caddy ]; then
      threads=$(sed -n "s/^Threads:[[:space:]]*//p" "$status")
    fi
  done
  peak=$(cat $cg/pids.peak 2>/dev/null || cat $cg/pids.current)
  limited=$(sed -n "s/^max //p" $cg/pids.events 2>/dev/null || echo 0)
  echo "$zombies $threads $(cat $cg/pids.current) $peak ${limited:-0}"
')
set -- $report
zombies=$1 threads=$2 current=$3 peak=$4 limited=$5
echo "proxy-runtime: caddy threads=$threads pids current=$current peak=$peak limit=$pids_limit zombies=$zombies"

[ "$client_status" = 0 ] || fail "concurrent load client failed ($client_status)"
[ "$health_status" = 0 ] || fail "service healthcheck failed under load"
[ "$zombies" = 0 ] || fail "$zombies zombie processes in the proxy container; PID 1 does not reap (init: true missing?)"
[ "$limited" = 0 ] || fail "pids_limit was hit $limited times"
[ "$peak" -le $((pids_limit / 2)) ] || fail "pids peak $peak exceeds half of pids_limit $pids_limit"
if docker logs "$name" 2>&1 | grep -q 'fatal error\|failed to create new OS thread'; then
  docker logs --tail 30 "$name" >&2 || true
  fail "Go runtime fatal error in proxy logs"
fi
echo "proxy-runtime: OK: $healthcheck_runs healthchecks and concurrent load within service limits; no zombies; caddy alive"
