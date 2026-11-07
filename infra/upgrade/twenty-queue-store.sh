#!/bin/sh
# Migrate Twenty's queue/cache store from Redis 7.4 to Valkey.
#
# Valkey cannot load the RDB format 12 that Redis 7.4 writes ("Can't handle
# RDB format version 12") and exits, so the new twenty-redis service would
# restart forever on an old volume. The store holds only BullMQ queues, the
# cache and pub/sub state; twenty-server registers its cron schedulers again
# at every start. The migration therefore drains the queues with the old
# containers and then empties the volume:
#
#   1. stop twenty-server, so no request creates new jobs,
#   2. start the existing (old) twenty-worker until no job is waiting, active,
#      prioritized, paused or delayed (cron scheduler instances excepted),
#      bounded by LEONAID_QUEUE_DRAIN_TIMEOUT seconds (default 300),
#   3. stop the old worker and Redis, remove the Redis container and delete
#      the volume content. Compose then starts Valkey on the empty volume.
#
# Lost by design: completed and failed job history (Twenty keeps it for 4 h /
# 7 days) and the cache. Pending jobs are never dropped silently: if some
# remain after the timeout the migration stops and leaves the volume intact,
# unless LEONAID_QUEUE_DISCARD_PENDING=true is set.
#
# Usage: infra/upgrade/twenty-queue-store.sh <status|migrate|require-current> [ROOT]
# The Compose project comes from LEONAID_COMPOSE_PROJECT (required).
# The script addresses containers by their Compose labels, so it works with
# whatever compose files and overlays created them.
set -eu

root=${2:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

action=${1:-}
project=${LEONAID_COMPOSE_PROJECT:?LEONAID_COMPOSE_PROJECT is required (use ./leonaid, never a default project)}
volume="${project}_twenty-redis-data"
drain_timeout=${LEONAID_QUEUE_DRAIN_TIMEOUT:-300}
discard_pending=${LEONAID_QUEUE_DISCARD_PENDING:-false}
inspector="${project}-twenty-queue-inspect"

case "$drain_timeout" in
  '' | *[!0-9]*)
    echo "twenty-queue-store: ERROR: LEONAID_QUEUE_DRAIN_TIMEOUT must be a number of seconds" >&2
    exit 64
    ;;
esac

fail() {
  echo "twenty-queue-store: ERROR: $*" >&2
  exit 1
}

# Counts jobs that still have to run. Scheduler instances (job ids
# "repeat:<scheduler>:<time>") are excluded: twenty-server recreates them.
# shellcheck disable=SC2016
pending_script='
local total = 0
local details = {}
local seen = {}
for _, pattern in ipairs({"bull:*:meta", "bull:*:id"}) do
  for _, key in ipairs(redis.call("KEYS", pattern)) do
    local queue = string.match(key, "^(.*):[^:]+$")
    if queue and not seen[queue] then
      seen[queue] = true
      local pending = redis.call("LLEN", queue .. ":wait")
        + redis.call("LLEN", queue .. ":active")
        + redis.call("LLEN", queue .. ":paused")
        + redis.call("ZCARD", queue .. ":prioritized")
        + redis.call("ZCARD", queue .. ":waiting-children")
      for _, id in ipairs(redis.call("ZRANGE", queue .. ":delayed", 0, -1)) do
        if string.sub(id, 1, 7) ~= "repeat:" then
          pending = pending + 1
        end
      end
      if pending > 0 then
        total = total + pending
        table.insert(details, queue .. "=" .. pending)
      end
    end
  end
end
return {total, table.concat(details, " ")}
'

service_container() {
  docker ps -aq --no-trunc \
    --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$1" \
    --filter "label=com.docker.compose.oneoff=False" | head -n 1
}

is_running() {
  [ -n "$1" ] &&
    [ "$(docker inspect --format '{{.State.Running}}' "$1" 2>/dev/null)" = true ]
}

# Prints the server_name of a running store, "redis" when INFO has none.
live_server() {
  info=$(docker exec "$1" redis-cli INFO server 2>/dev/null) || return 1
  name=$(printf '%s\n' "$info" | tr -d '\r' | sed -n 's/^server_name://p')
  printf '%s\n' "${name:-redis}"
}

# Prints the format of the persisted store: absent, empty, valkey,
# redis-compatible (RDB <= 11, readable by Valkey), legacy-redis (RDB >= 12)
# or unknown.
volume_format() {
  docker volume inspect "$volume" >/dev/null 2>&1 || {
    echo absent
    return 0
  }
  header=$(docker run --rm --network none \
    --volume "$volume:/data:ro" \
    "$ALPINE_IMAGE" \
    sh -eu -c '
      if [ -d /data/appendonlydir ]; then echo aof; exit 0; fi
      if [ -f /data/dump.rdb ]; then head -c 9 /data/dump.rdb; fi')
  case "$header" in
    '') echo empty ;;
    aof) echo unknown ;;
    VALKEY*) echo valkey ;;
    REDIS[0-9][0-9][0-9][0-9])
      rdb_version=$(expr "${header#REDIS}" + 0)
      if [ "$rdb_version" -ge 12 ]; then
        echo legacy-redis
      else
        echo redis-compatible
      fi
      ;;
    *) echo unknown ;;
  esac
}

store_state() {
  redis=$(service_container twenty-redis)
  if is_running "$redis"; then
    if server=$(live_server "$redis"); then
      case "$server" in
        valkey) echo valkey ;;
        *) echo legacy-redis ;;
      esac
      return 0
    fi
  fi
  volume_format
}

wait_for_ping() {
  deadline=$(($(date +%s) + 60))
  until docker exec "$1" redis-cli ping 2>/dev/null | grep -Fx PONG >/dev/null; do
    if ! is_running "$1" || [ "$(date +%s)" -ge "$deadline" ]; then
      return 1
    fi
    sleep 1
  done
}

# Prints "<total>" and on a second line the per-queue details.
count_pending() {
  docker exec "$1" redis-cli EVAL "$pending_script" 0 | tr -d '\r'
}

started_containers=
start_container() {
  [ -n "$1" ] || return 1
  if ! is_running "$1"; then
    docker start "$1" >/dev/null
    started_containers="$started_containers $1"
  fi
}

stop_started() {
  for container in $started_containers; do
    docker stop "$container" >/dev/null 2>&1 || true
  done
  started_containers=
}

# Drains the queues on the old, still existing Redis container. Prints the
# remaining number of pending jobs.
drain_live() {
  redis=$1
  server_container=$(service_container twenty-server)
  worker_container=$(service_container twenty-worker)
  if is_running "$server_container"; then
    echo "twenty-queue-store: stopping twenty-server so no new jobs are queued" >&2
    docker stop "$server_container" >/dev/null
  fi
  result=$(count_pending "$redis")
  pending=$(printf '%s\n' "$result" | sed -n 1p)
  if [ "$pending" -gt 0 ] && [ -n "$worker_container" ]; then
    echo "twenty-queue-store: draining $pending pending jobs with the existing twenty-worker (at most ${drain_timeout}s): $(printf '%s\n' "$result" | sed -n 2p)" >&2
    # The old worker needs its database; start what is not running yet.
    start_container "$(service_container twenty-postgres)" || true
    start_container "$worker_container"
    deadline=$(($(date +%s) + drain_timeout))
    empty_polls=0
    while [ "$empty_polls" -lt 2 ] && [ "$(date +%s)" -lt "$deadline" ]; do
      sleep 2
      result=$(count_pending "$redis")
      pending=$(printf '%s\n' "$result" | sed -n 1p)
      if [ "$pending" -eq 0 ]; then
        empty_polls=$((empty_polls + 1))
      else
        empty_polls=0
      fi
    done
  fi
  # Stop the worker whether this script started it or not: it must not take
  # new jobs while the store is replaced.
  if is_running "$worker_container"; then
    docker stop "$worker_container" >/dev/null
  fi
  # Count before stop_started: when the stack was stopped, this script started
  # the old Redis itself, and stop_started would stop it again.
  result=$(count_pending "$redis")
  stop_started
  printf '%s\n' "$result"
}

# Without an old Redis container, load the RDB read-only into a throwaway,
# network-less Valkey that tolerates the newer format, only to count jobs.
inspect_volume() {
  docker rm -f "$inspector" >/dev/null 2>&1 || true
  docker run --detach --name "$inspector" --network none \
    --user 999:1000 \
    --security-opt no-new-privileges:true \
    --memory 512m \
    --volume "$volume:/data:ro" \
    "$VALKEY_IMAGE" \
    valkey-server --rdb-version-check relaxed --save '' --appendonly no >/dev/null
  if ! wait_for_ping "$inspector"; then
    docker logs --tail 20 "$inspector" >&2 || true
    docker rm -f "$inspector" >/dev/null 2>&1 || true
    fail "cannot inspect $volume; it was left unchanged"
  fi
  result=$(count_pending "$inspector")
  docker rm -f "$inspector" >/dev/null
  printf '%s\n' "$result"
}

migrate() {
  state=$(store_state)
  case "$state" in
    absent | empty | valkey | redis-compatible)
      echo "twenty-queue-store: OK: $volume needs no migration ($state)"
      return 0
      ;;
    legacy-redis) ;;
    *) fail "$volume has an unknown format; refusing to touch it" ;;
  esac
  echo "twenty-queue-store: $volume holds a Redis 7.4 store; Valkey cannot load it"
  redis=$(service_container twenty-redis)
  live=false
  if [ -n "$redis" ]; then
    start_container "$redis" || true
    if wait_for_ping "$redis" && [ "$(live_server "$redis")" != valkey ]; then
      live=true
    else
      # A Valkey container that keeps failing on the old file.
      docker stop "$redis" >/dev/null 2>&1 || true
    fi
  fi
  if [ "$live" = true ]; then
    result=$(drain_live "$redis")
  else
    echo "twenty-queue-store: no old Redis container; inspecting the volume read-only" >&2
    result=$(inspect_volume)
  fi
  pending=$(printf '%s\n' "$result" | sed -n 1p)
  details=$(printf '%s\n' "$result" | sed -n 2p)
  case "$pending" in
    '' | *[!0-9]*) fail "could not count pending jobs in $volume" ;;
  esac
  if [ "$pending" -gt 0 ]; then
    if [ "$discard_pending" != true ]; then
      fail "$pending Twenty jobs are still pending ($details). The volume is unchanged. Retry later, raise LEONAID_QUEUE_DRAIN_TIMEOUT, or set LEONAID_QUEUE_DISCARD_PENDING=true to drop them."
    fi
    echo "twenty-queue-store: WARNING: dropping $pending pending Twenty jobs ($details) as requested" >&2
  fi
  if [ -n "$redis" ]; then
    docker stop "$redis" >/dev/null 2>&1 || true
    docker rm "$redis" >/dev/null
  fi
  docker run --rm --network none \
    --volume "$volume:/data" \
    "$ALPINE_IMAGE" \
    find /data -mindepth 1 -delete
  state=$(volume_format)
  [ "$state" = empty ] || fail "$volume is not empty after the reset ($state)"
  echo "twenty-queue-store: OK: drained and reset $volume; Valkey starts on an empty store"
  echo "twenty-queue-store:     completed/failed job history and the cache were dropped; twenty-server registers its cron jobs again at start"
}

case "$action" in
  status)
    store_state
    ;;
  migrate)
    migrate
    ;;
  require-current)
    state=$(store_state)
    case "$state" in
      absent | empty | valkey | redis-compatible) ;;
      *)
        fail "$volume holds a $state store; run ./leonaid pilot-release, which migrates it in maintenance mode"
        ;;
    esac
    ;;
  *)
    echo "Usage: infra/upgrade/twenty-queue-store.sh <status|migrate|require-current> [ROOT]" >&2
    exit 64
    ;;
esac
