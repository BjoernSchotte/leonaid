#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

container_proof=$(mktemp -d)

cleanup() {
  status=$?
  rm -rf "$container_proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$root:/workspace:ro" \
  --volume "$container_proof:/boundary" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot/evidence.py init --root /boundary

for directory in \
  "$container_proof/.local/pilot" \
  "$container_proof/.local/pilot/intake" \
  "$container_proof/.local/pilot/evidence" \
  "$container_proof/.local/pilot/backups" \
  "$container_proof/.local/pilot/manifests"; do
  # GNU stat accepts `-f` with a different meaning and would print a complete
  # filesystem report instead of failing. Try the GNU mode format first and
  # fall back to the BSD/macOS format.
  actual=$(stat -c '%a' "$directory" 2>/dev/null || stat -f '%Lp' "$directory")
  if [ "$actual" != "700" ]; then
    echo "pilot-data-boundary-test: ERROR: $directory ist Modus $actual statt 700" >&2
    exit 1
  fi
done

docker run --rm \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$PLAYWRIGHT_IMAGE" \
  python3 -m tools.pilot.test /workspace

docker run --rm \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/ci/sanitize_artifacts_test.py /workspace

echo "pilot-data-boundary-test: OK: Host-, Docker-, Git- und Artefaktgrenze bewiesen"
