# Measure only a fixed label and elapsed seconds; never print command arguments.
# A subshell keeps nested timers independent. The EXIT trap retains errexit,
# including failures inside shell functions; an if/else wrapper would disable it.
phase() (
  phase_label=$1
  shift
  phase_started=$(date +%s)
  trap 'phase_status=$?; printf "test-phase: %s seconds=%s exit=%s\n" "$phase_label" "$(( $(date +%s) - phase_started ))" "$phase_status"; exit "$phase_status"' EXIT
  "$@"
)
