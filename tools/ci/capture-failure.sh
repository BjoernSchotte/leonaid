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

# Reuse the exact Compose file set and env file the suite started this project
# with, read from the project's own containers. A different file set (e.g.
# compose.yml without the suite's isolation/overlay files) makes `compose run`
# create networks the suite's model does not declare, from Docker's default
# address pools, and the suite's `down` then leaks them.
model=$(docker ps --all \
  --filter "label=com.docker.compose.project=$project" \
  --filter "label=com.docker.compose.oneoff=False" \
  --format '{{.Label "com.docker.compose.project.config_files"}}|{{.Label "com.docker.compose.project.environment_file"}}' \
  2>/dev/null | head -n 1) || model=""
config_files=${model%%|*}
environment_files=${model#*|}
if [ -z "$environment_files" ]; then environment_files="$root/.env.local"; fi
if [ -z "$model" ] || [ -z "$config_files" ]; then
  echo "No containers of $project; Compose diagnostics skipped." \
    >"$destination/services.txt"
else
  set --
  old_ifs=$IFS
  IFS=,
  for file in $config_files; do set -- "$@" --file "$file"; done
  for file in $environment_files; do set -- "$@" --env-file "$file"; done
  IFS=$old_ifs
  docker compose --project-name "$project" "$@" \
    ps --all >"$destination/services.txt" 2>&1 || true
  docker compose --project-name "$project" "$@" \
    logs --no-color >"$destination/compose.log" 2>&1 || true
  docker compose --project-name "$project" "$@" \
    run --rm --user "$(id -u):$(id -g)" --no-deps \
    --env-from-file "$root/.env.local" \
    --env PYTHONPATH=/repo/src \
    --volume "$root:/repo:ro" \
    --volume "$destination:/ci" \
    --entrypoint python \
    api /repo/tools/ci/runtime_diagnostics.py /ci/runtime-diagnostics.json \
    >"$destination/runtime-diagnostics.log" 2>&1 || true
fi

docker run --rm --user "$(id -u):$(id -g)" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof:ro" \
  --volume "$destination:/ci" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/ci/sanitize_artifacts.py \
  /ci /workspace/.env.local --env-directory /proof \
  >"$destination/sanitize.log" 2>&1 || {
    echo "ci-capture-failure: ERROR: artifacts could not be redacted safely" >&2
    find "$destination" -type f -delete
    printf '%s\n' \
      "Artifacts discarded for security reasons: redaction check failed." \
      >"$destination/SANITIZATION-FAILED.txt"
    exit 1
  }
