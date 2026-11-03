#!/bin/sh
# Free disk on an ephemeral GitHub-hosted runner by deleting preinstalled
# toolchains LeonAid never uses (every LeonAid toolchain runs in a pinned
# container). Small AWS-hosted runners start with about 14 GB free; jobs that
# build or load LeonAid images need more. Deleting frees about 18 GB.
#
# Usage: free-runner-disk.sh start   delete in the background, return at once
#        free-runner-disk.sh wait    block until deletion ended, fail on error
# Refuses to run outside GitHub Actions: it deletes system directories.
set -eu

if [ "${GITHUB_ACTIONS:-}" != true ] || [ -z "${RUNNER_TEMP:-}" ]; then
  echo "free-runner-disk: ERROR: only for ephemeral GitHub Actions runners" >&2
  exit 64
fi

state="$RUNNER_TEMP/leonaid-free-disk"
case ${1:-} in
  start)
    if [ -e "$state" ]; then
      echo "free-runner-disk: already started in this job"
      exit 0
    fi
    mkdir -p "$state"
    date +%s >"$state/started"
    df -h / | tail -n 1 | sed 's/^/free-runner-disk: before: /' >"$state/log"
    # Deletion is bound by file-system metadata (the Android SDK alone has
    # hundreds of thousands of files), so second-level entries are removed in
    # parallel before the now nearly empty top-level directories.
    nohup sudo sh -c '
      state=$1
      shift
      status=0
      for directory in "$@"; do
        if [ -d "$directory" ]; then
          find "$directory" -mindepth 2 -maxdepth 2 -print0
        fi
      done | xargs -0 -r -n 8 -P 8 rm -rf >>"$state/log" 2>&1 || status=$?
      rm -rf "$@" >>"$state/log" 2>&1 || status=$?
      printf "%s\n" "$status" >"$state/status"
    ' free-runner-disk "$state" \
      /usr/local/lib/android \
      /usr/share/dotnet \
      /opt/ghc \
      /usr/local/.ghcup \
      /opt/hostedtoolcache/CodeQL \
      </dev/null >/dev/null 2>&1 &
    ;;
  wait)
    if [ ! -f "$state/started" ]; then
      echo "free-runner-disk: ERROR: start was not run in this job" >&2
      exit 70
    fi
    timeout 600 sh -c 'until test -f "$1/status"; do sleep 1; done' wait "$state"
    df -h / | tail -n 1 | sed 's/^/free-runner-disk: after:  /' >>"$state/log"
    cat "$state/log"
    echo "free-runner-disk: $(( $(date +%s) - $(cat "$state/started") )) seconds since start"
    test "$(cat "$state/status")" = 0
    ;;
  *)
    echo "free-runner-disk: ERROR: expected start or wait" >&2
    exit 64
    ;;
esac
