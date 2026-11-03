#!/bin/sh
# Free disk on an ephemeral GitHub-hosted runner by deleting preinstalled
# toolchains LeonAid never uses (every LeonAid toolchain runs in a pinned
# container). The Security job builds all own images and scans every pinned
# third-party image on one runner; without this, the root disk runs full.
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
    mkdir -p "$state"
    df -h / | tail -n 1 | sed 's/^/free-runner-disk: before: /' >"$state/log"
    nohup sh -c '
      status=0
      sudo rm -rf \
        /usr/local/lib/android \
        /usr/share/dotnet \
        /opt/ghc \
        /usr/local/.ghcup \
        /opt/hostedtoolcache/CodeQL >>"$1/log" 2>&1 || status=$?
      printf "%s\n" "$status" >"$1/status"
    ' free-runner-disk "$state" </dev/null >/dev/null 2>&1 &
    ;;
  wait)
    timeout 600 sh -c 'until test -f "$1/status"; do sleep 1; done' wait "$state"
    df -h / | tail -n 1 | sed 's/^/free-runner-disk: after:  /' >>"$state/log"
    cat "$state/log"
    test "$(cat "$state/status")" = 0
    ;;
  *)
    echo "free-runner-disk: ERROR: expected start or wait" >&2
    exit 64
    ;;
esac
