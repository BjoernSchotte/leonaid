#!/bin/sh
# Print free runner disk and Docker storage at a named checkpoint.
# Diagnostics only: never fails the calling job.
set -u
label=${1:-checkpoint}
echo "disk-report: $label"
df -h / 2>/dev/null || true
docker system df 2>/dev/null || true
if [ -n "${BUILDX_BUILDER:-}" ]; then
  docker buildx du --builder "$BUILDX_BUILDER" 2>/dev/null | tail -n 1 || true
fi
exit 0
