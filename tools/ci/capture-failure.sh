#!/bin/sh
set -u

root=$1
proof=$2
project=$3
artifact_directory=${LEONAID_CI_ARTIFACT_DIR:-}
. "$root/infra/locks/images.env"

if [ -z "$artifact_directory" ]; then
  exit 0
fi

case "$artifact_directory" in
  /*) ;;
  *) artifact_directory="$root/$artifact_directory" ;;
esac

destination="$artifact_directory/runtime-$project"
mkdir -p "$destination/proof"

if [ -d "$proof" ]; then
  find "$proof" -type f ! -name '*.env' | while IFS= read -r source; do
    relative=${source#"$proof/"}
    mkdir -p "$destination/proof/$(dirname "$relative")"
    cp "$source" "$destination/proof/$relative"
  done
fi

docker compose \
  --project-name "$project" \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
  ps >"$destination/services.txt" 2>&1 || true
docker compose \
  --project-name "$project" \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
  logs --no-color >"$destination/compose.log" 2>&1 || true

docker compose \
  --project-name "$project" \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
  run --rm --no-deps \
  --env-from-file "$root/.env.local" \
  --env PYTHONPATH=/repo/src \
  --volume "$root:/repo:ro" \
  --volume "$destination:/ci" \
  --entrypoint python \
  api /repo/tools/ci/runtime_diagnostics.py /ci/runtime-diagnostics.json \
  >"$destination/runtime-diagnostics.log" 2>&1 || true

docker run --rm \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof:ro" \
  --volume "$destination:/ci" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/ci/sanitize_artifacts.py \
  /ci /workspace/.env.local --env-directory /proof \
  >"$destination/sanitize.log" 2>&1 || {
    echo "ci-capture-failure: ERROR: Artefakte konnten nicht sicher redigiert werden" >&2
    find "$destination" -type f -delete
    printf '%s\n' \
      "Artefakte aus Sicherheitsgründen verworfen: Redaktionsprüfung fehlgeschlagen." \
      >"$destination/SANITIZATION-FAILED.txt"
    exit 1
  }
