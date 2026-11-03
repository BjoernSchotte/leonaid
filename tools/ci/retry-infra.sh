#!/bin/sh
# Retry an infrastructure command (toolchain bootstrap, image pull) with
# backoff. Registry, bun, uv and apt downloads fail transiently on hosted
# runners; a test must never be retried, so only allowlisted commands run.
set -eu

case "$*" in
  "./leonaid bootstrap" | \
    "sh tools/ci/bootstrap-prefetch.sh toolchains" | \
    "sh tools/ci/bootstrap-prefetch.sh seed" | \
    "sh tools/ci/bootstrap-prefetch.sh browser" | \
    "docker pull "*) ;;
  *)
    echo "ci-retry-infra: ERROR: not an allowlisted infrastructure command: $*" >&2
    exit 64
    ;;
esac
case "$*" in
  *";"* | *"&"* | *"|"* | *'$('* | *'`'*)
    echo "ci-retry-infra: ERROR: compound commands are not retried: $*" >&2
    exit 64
    ;;
esac

attempts=${LEONAID_INFRA_ATTEMPTS:-3}
delay=${LEONAID_INFRA_DELAY:-15}
attempt=1
while :; do
  status=0
  "$@" || status=$?
  if [ "$status" -eq 0 ]; then
    exit 0
  fi
  if [ "$attempt" -ge "$attempts" ]; then
    echo "ci-retry-infra: ERROR: '$*' failed $attempt times (last status $status)" >&2
    exit "$status"
  fi
  echo "ci-retry-infra: WARNING: '$*' failed with status $status; attempt $((attempt + 1))/$attempts in ${delay}s" >&2
  if [ -n "${GITHUB_ACTIONS:-}" ]; then
    echo "::warning title=Infrastructure retry::$* failed with status $status (attempt $attempt/$attempts)"
  fi
  sleep "$delay"
  attempt=$((attempt + 1))
  delay=$((delay * 2))
done
