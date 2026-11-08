#!/bin/sh
# CI unit tests: every test of tests/unit exactly once, in parallel lanes.
#
# The exhaustive survey disclosure solver proof is about 85 % of the unit
# time (319 s of 345 s on a 4-vCPU runner, run 42468977036). It runs as
# LEONAID_UNIT_SOLVER_SHARDS deterministic shards (tools/dx/pytest_shard.py:
# position modulo count, so the shards partition the file) beside one lane
# with every other unit test. `./leonaid test-unit` runs the same tests in
# one process. The shards are balanced by the measured seconds per test in
# tests/unit/test_survey_disclosure_solver.weights.json (a test missing there
# only shifts the balance, never the coverage).
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"
solver=tests/unit/test_survey_disclosure_solver.py
shards=${LEONAID_UNIT_SOLVER_SHARDS:-4}
case "$shards" in '' | *[!0-9]* | 0) shards=4 ;; esac

run_python() {
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -e PYTHONPATH=/workspace/src \
    -e UV_CACHE_DIR=/workspace/.cache/uv \
    -e UV_LINK_MODE=copy \
    -v "$root:/workspace" \
    -w /workspace \
    "$UV_IMAGE" \
    "$@"
}

lanes=$(mktemp -d)
trap 'rm -rf "$lanes"' EXIT HUP INT TERM

# lane NAME COMMAND...: run in the background, output and status to files.
lane() {
  name=$1
  shift
  (
    status=0
    "$@" >"$lanes/$name.log" 2>&1 || status=$?
    echo "$status" >"$lanes/$name.status"
  ) &
}

lane rest run_python uv run --frozen --no-sync pytest -p no:cacheprovider \
  tests/unit --ignore="$solver"
index=0
while [ "$index" -lt "$shards" ]; do
  lane "solver-$index" run_python env PYTHONPATH=/workspace:/workspace/src \
    LEONAID_PYTEST_SHARD="$index/$shards" \
    LEONAID_PYTEST_WEIGHTS=/workspace/tests/unit/test_survey_disclosure_solver.weights.json \
    uv run --frozen --no-sync pytest -q -p no:cacheprovider -p tools.dx.pytest_shard \
    "$solver"
  index=$((index + 1))
done
wait

failed=""
for status_file in "$lanes"/*.status; do
  name=$(basename "$status_file" .status)
  echo "ci-unit: ---- $name ----"
  cat "$lanes/$name.log"
  if [ "$(cat "$status_file")" != 0 ]; then
    failed="$failed $name"
  fi
done
expected=$((shards + 1))
found=$(find "$lanes" -name '*.status' | wc -l)
if [ "$found" -ne "$expected" ]; then
  echo "ci-unit: ERROR: $found of $expected lanes reported a result" >&2
  exit 1
fi
if [ -n "$failed" ]; then
  echo "ci-unit: ERROR: failed lanes:$failed" >&2
  exit 1
fi
echo "ci-unit: OK: unit tests and $shards solver shards"
