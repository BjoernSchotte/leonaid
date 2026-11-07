#!/bin/sh
# Leak check between the shards of one packed CI leg.
#
# Several shards now share one runner. A shard whose teardown leaves Compose
# containers, networks or volumes behind would make the next shard fail with
# a port, subnet or disk error, attributed to the wrong shard. This check
# names the shard that leaked, removes exactly the leaked projects and fails
# that shard.
#
# Usage: leak-check.sh snapshot FILE
#        leak-check.sh check FILE SHARD
# Only on ephemeral GitHub Actions runners: on a developer machine other
# worktrees start and stop their own stacks at any time, so a difference
# there proves nothing and must never be removed. Outside CI both commands
# do nothing and succeed.
set -eu

[ "${GITHUB_ACTIONS:-}" = true ] || exit 0

projects() {
  {
    docker ps -a --filter label=com.docker.compose.project \
      --format '{{.Label "com.docker.compose.project"}}'
    docker network ls --filter label=com.docker.compose.project \
      --format '{{.Label "com.docker.compose.project"}}'
    docker volume ls --filter label=com.docker.compose.project \
      --format '{{.Label "com.docker.compose.project"}}'
  } | sed '/^$/d' | sort -u
}

case ${1:-} in
  snapshot)
    projects >"${2:?snapshot file required}"
    ;;
  check)
    before=${2:?snapshot file required}
    shard=${3:?shard name required}
    now=$(mktemp)
    projects >"$now"
    leaked=$(comm -13 "$before" "$now")
    rm -f "$now"
    if [ -z "$leaked" ]; then
      exit 0
    fi
    for project in $leaked; do
      filter="label=com.docker.compose.project=$project"
      echo "ci-leak-check: ERROR: $shard left Compose project $project behind:" >&2
      docker ps -a --filter "$filter" --format '  container {{.Names}} {{.Status}}' >&2 || true
      docker network ls --filter "$filter" --format '  network {{.Name}}' >&2 || true
      docker volume ls --filter "$filter" --format '  volume {{.Name}}' >&2 || true
      containers=$(docker ps -aq --filter "$filter")
      # shellcheck disable=SC2086 # one word per id
      if [ -n "$containers" ]; then docker rm --force --volumes $containers >/dev/null || true; fi
      networks=$(docker network ls -q --filter "$filter")
      # shellcheck disable=SC2086
      if [ -n "$networks" ]; then docker network rm $networks >/dev/null || true; fi
      volumes=$(docker volume ls -q --filter "$filter")
      # shellcheck disable=SC2086
      if [ -n "$volumes" ]; then docker volume rm --force $volumes >/dev/null || true; fi
    done
    exit 1
    ;;
  *)
    echo "ci-leak-check: ERROR: expected snapshot or check" >&2
    exit 64
    ;;
esac
