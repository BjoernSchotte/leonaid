#!/usr/bin/env bash
set -uo pipefail

# Usage: capture-command.sh LOG COMMAND...
# LEONAID_CI_STEP_SECONDS (optional) bounds the command: after that many
# seconds its whole process group gets SIGTERM, 30 s later SIGKILL, and the
# step exits 124 with "time limit" in the log. A job killed by GitHub's
# timeout-minutes loses its logs and artifacts; this limit fires first, so
# run-job.sh still collects diagnostics, sanitizes and uploads the evidence.
log=${1:?log file is required}
shift
limit=${LEONAID_CI_STEP_SECONDS:-}
case "$limit" in
  "" | *[!0-9]*) limit="" ;;
esac
temporary=$(mktemp -d) || exit 74
watchdog_pid=""
cleanup() {
  if [ -n "$watchdog_pid" ]; then kill "$watchdog_pid" 2>/dev/null || true; fi
  rm -rf "$temporary"
}
trap cleanup EXIT
mkfifo "$temporary/stdout" "$temporary/stderr" || exit 74

# Keep streams separate: a stderr notice can otherwise split a UTF-8 stdout
# character. Tee still streams both channels to the CI console during the run.
tee "$temporary/stdout.log" <"$temporary/stdout" &
stdout_pid=$!
tee "$temporary/stderr.log" <"$temporary/stderr" >&2 &
stderr_pid=$!
# Own process group: the watchdog can stop every descendant at once.
setsid "$@" >"$temporary/stdout" 2>"$temporary/stderr" &
command_pid=$!
if [ -n "$limit" ]; then
  # The watchdog holds no output stream, and stopping it stops its sleep.
  (
    pause() {
      sleep "$1" &
      sleeper=$!
      wait "$sleeper"
    }
    trap 'kill "$sleeper" 2>/dev/null; exit 0' TERM
    pause "$limit"
    if kill -0 "$command_pid" 2>/dev/null; then
      : >"$temporary/timed-out"
      kill -TERM -- "-$command_pid" 2>/dev/null || true
      pause 30
      kill -KILL -- "-$command_pid" 2>/dev/null || true
    fi
  ) </dev/null >/dev/null 2>&1 &
  watchdog_pid=$!
fi
wait "$command_pid"
status=$?
if [ -e "$temporary/timed-out" ]; then
  status=124
  # The leader is gone; nothing left in its group may keep running.
  kill -KILL -- "-$command_pid" 2>/dev/null || true
  echo "capture-command: time limit of ${limit}s reached; the process group was stopped" >&2
fi
# A descendant outside the process group may still hold a stream open; do
# not let it hang the step: give the readers 30 s, then abandon them.
for _ in $(seq 1 30); do
  kill -0 "$stdout_pid" 2>/dev/null || kill -0 "$stderr_pid" 2>/dev/null || break
  sleep 1
done
for reader in "$stdout_pid" "$stderr_pid"; do
  if kill -0 "$reader" 2>/dev/null; then
    kill "$reader" 2>/dev/null || true
    echo "capture-command: abandoned an output stream still held open" >>"$temporary/stderr.log"
  else
    wait "$reader" || status=74
  fi
done
if [ "$status" -eq 124 ]; then
  printf 'capture-command: time limit of %ss reached; the process group was stopped\n' \
    "$limit" >>"$temporary/stderr.log"
fi

# Preserve original bytes, including invalid input, for the unchanged sanitizer.
# Channel order is explicit; this file does not claim cross-stream chronology.
{
  printf '%s\n' '--- stdout ---' || status=74
  cat "$temporary/stdout.log" || status=74
  printf '\n%s\n' '--- stderr ---' || status=74
  cat "$temporary/stderr.log" || status=74
} >"$log" || status=74
exit "$status"
