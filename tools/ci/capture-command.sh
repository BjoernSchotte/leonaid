#!/usr/bin/env bash
set -uo pipefail

log=${1:?log file is required}
shift
temporary=$(mktemp -d) || exit 74
trap 'rm -rf "$temporary"' EXIT
mkfifo "$temporary/stdout" "$temporary/stderr" || exit 74

# Keep streams separate: a stderr notice can otherwise split a UTF-8 stdout
# character. Tee still streams both channels to the CI console during the run.
tee "$temporary/stdout.log" <"$temporary/stdout" &
stdout_pid=$!
tee "$temporary/stderr.log" <"$temporary/stderr" >&2 &
stderr_pid=$!
"$@" >"$temporary/stdout" 2>"$temporary/stderr"
status=$?
wait "$stdout_pid" || status=74
wait "$stderr_pid" || status=74

# Preserve original bytes, including invalid input, for the unchanged sanitizer.
# Channel order is explicit; this file does not claim cross-stream chronology.
{
  printf '%s\n' '--- stdout ---' || status=74
  cat "$temporary/stdout.log" || status=74
  printf '\n%s\n' '--- stderr ---' || status=74
  cat "$temporary/stderr.log" || status=74
} >"$log" || status=74
exit "$status"
