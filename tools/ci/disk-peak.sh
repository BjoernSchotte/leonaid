#!/bin/sh
# Record the peak disk use of / while a packed CI leg runs its shards, so the
# free-runner-disk.sh skip threshold (LEONAID_FREE_DISK_MIN_GB) rests on data.
# Usage: disk-peak.sh start   sample every 5 s in the background
#        disk-peak.sh stop    print start, peak and end use; never fails
set -u

state="${RUNNER_TEMP:-/tmp}/leonaid-disk-peak"
used() { df -Pk / | awk 'NR == 2 { print $3 }'; }
case ${1:-} in
  start)
    mkdir -p "$state"
    used >"$state/start"
    used >"$state/peak"
    nohup sh -c '
      while :; do
        now=$(df -Pk / | awk "NR == 2 { print \$3 }")
        peak=$(cat "$1/peak" 2>/dev/null || echo 0)
        if [ "$now" -gt "$peak" ]; then echo "$now" >"$1/peak"; fi
        sleep 5
      done
    ' disk-peak "$state" </dev/null >/dev/null 2>&1 &
    echo $! >"$state/pid"
    ;;
  stop)
    if [ -f "$state/pid" ]; then kill "$(cat "$state/pid")" 2>/dev/null || true; fi
    if [ -f "$state/peak" ]; then
      awk -v start="$(cat "$state/start")" -v peak="$(cat "$state/peak")" -v end="$(used)" \
        'BEGIN { printf "disk-peak: used start %.1f GB, peak %.1f GB, end %.1f GB (peak growth %.1f GB)\n", start / 1048576, peak / 1048576, end / 1048576, (peak - start) / 1048576 }'
    else
      echo "disk-peak: not started"
    fi
    ;;
  *)
    echo "disk-peak: expected start or stop" >&2
    ;;
esac
exit 0
