#!/usr/bin/env bash
set -uo pipefail

label=${1:?job label is required}
shift
root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"
artifact_directory=${LEONAID_CI_ARTIFACT_DIR:-"$root/.artifacts/ci/$label"}
case "$artifact_directory" in
  /*) ;;
  *) artifact_directory="$root/$artifact_directory" ;;
esac
case "$artifact_directory" in
  "$root"/*) artifact_relative=${artifact_directory#"$root/"} ;;
  *)
    echo "ci-run-job: ERROR: Artefaktpfad muss im Repository liegen" >&2
    exit 64
    ;;
esac
mkdir -p "$artifact_directory"
export LEONAID_CI_ARTIFACT_DIR="$artifact_directory"

set +e
"$@" 2>&1 | tee "$artifact_directory/command.log"
status=${PIPESTATUS[0]}
set -e

{
  printf 'job=%s\n' "$label"
  printf 'status=%s\n' "$status"
  printf 'commit=%s\n' "$(git -C "$root" rev-parse HEAD)"
  printf 'finished_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$artifact_directory/summary.txt"

if [ "$status" -ne 0 ]; then
  docker compose ls --format json \
    >"$artifact_directory/compose-projects.json" 2>&1 || true
  docker ps --all --format \
    '{{.Names}}\t{{.Image}}\t{{.Status}}' \
    >"$artifact_directory/docker-containers.txt" 2>&1 || true
fi

if ! docker run --rm \
  --volume "$root:/workspace" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python /workspace/tools/ci/sanitize_artifacts.py \
  "/workspace/$artifact_relative" /workspace/.env.local; then
  find "$artifact_directory" -type f -delete
  printf '%s\n' \
    "Artefakte aus Sicherheitsgründen verworfen: Redaktionsprüfung fehlgeschlagen." \
    >"$artifact_directory/SANITIZATION-FAILED.txt"
  exit 70
fi
exit "$status"
