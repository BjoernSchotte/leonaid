#!/bin/sh
# Record the peak disk and memory use of a packed CI leg while it runs its
# shards: the data for the free-runner-disk.sh skip threshold
# (LEONAID_FREE_DISK_MIN_GB) and for running light shards concurrently.
# Usage: disk-peak.sh start   sample every 5 s in the background
#        disk-peak.sh stop    print start, peak and end use; never fails
set -u

state="${RUNNER_TEMP:-/tmp}/leonaid-disk-peak"
used() { df -Pk / | awk 'NR == 2 { print $3 }'; }
# Memory in use (MemTotal - MemAvailable), KiB.
memory() { awk '/^MemTotal:/ { t = $2 } /^MemAvailable:/ { a = $2 } END { print t - a }' /proc/meminfo; }
case ${1:-} in
  start)
    mkdir -p "$state"
    used >"$state/start"
    used >"$state/peak"
    memory >"$state/memory-start"
    memory >"$state/memory-peak"
    nohup sh -c '
      while :; do
        now=$(df -Pk / | awk "NR == 2 { print \$3 }")
        peak=$(cat "$1/peak" 2>/dev/null || echo 0)
        if [ "$now" -gt "$peak" ]; then echo "$now" >"$1/peak"; fi
        mem=$(awk "/^MemTotal:/ { t = \$2 } /^MemAvailable:/ { a = \$2 } END { print t - a }" /proc/meminfo)
        mpeak=$(cat "$1/memory-peak" 2>/dev/null || echo 0)
        if [ "$mem" -gt "$mpeak" ]; then echo "$mem" >"$1/memory-peak"; fi
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
      awk -v start="$(cat "$state/memory-start")" -v peak="$(cat "$state/memory-peak")" \
        -v total="$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo)" \
        'BEGIN { printf "memory-peak: in use start %.1f GB, peak %.1f GB of %.1f GB\n", start / 1048576, peak / 1048576, total / 1048576 }'
    else
      echo "disk-peak: not started"
    fi
    ;;
  *)
    echo "disk-peak: expected start or stop" >&2
    ;;
esac
exit 0
