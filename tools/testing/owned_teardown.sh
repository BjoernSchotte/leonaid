# Sourced by real-system test suites after `compose --profile '*' down`.
#
# verify_owned_project_removed PROJECT [--keep-images]
#   Lists every container (including stopped one-off `compose run` containers),
#   network and volume that still carries PROJECT's Compose label. Any leftover
#   is printed by name, removed by that exact label and makes the call fail:
#   a leak is a harness bug that must surface, but it must not exhaust the
#   host's Docker address pools while someone looks into it. Finally the
#   "PROJECT-<service>" image tags are removed; project names are unique per
#   invocation. Content-hash tags shared by all checkouts
#   (leonaid-local/<service>:<hash>, see build_shared_images) are never
#   removed here; tools/testing/image_tags.py keeps the newest few per service.
#   --keep-images skips that for a mid-run reset that rebuilds nothing.
#   Returns 1 on leftovers or unreadable inventories, 0 otherwise.
#
# Only objects labelled com.docker.compose.project=PROJECT are touched, never
# a prune and never another project's resources.

verify_owned_project_removed() {
  teardown_project=$1
  teardown_label="label=com.docker.compose.project=$teardown_project"
  teardown_status=0
  teardown_keep_images=false
  case "${2:-}" in
    '') ;;
    --keep-images) teardown_keep_images=true ;;
    *)
      echo "test-isolation: unknown option '$2'" >&2
      return 1
      ;;
  esac
  case "$teardown_project" in
    leonaid-*) ;;
    *)
      echo "test-isolation: refusing teardown check for foreign project '$teardown_project'" >&2
      return 1
      ;;
  esac
  for teardown_inventory in containers networks volumes; do
    case "$teardown_inventory" in
      containers) teardown_remaining=$(docker ps -a --filter "$teardown_label" --format '{{.Names}}') || { teardown_status=1; continue; } ;;
      networks) teardown_remaining=$(docker network ls --filter "$teardown_label" --format '{{.Name}}') || { teardown_status=1; continue; } ;;
      volumes) teardown_remaining=$(docker volume ls --filter "$teardown_label" --format '{{.Name}}') || { teardown_status=1; continue; } ;;
    esac
    [ -n "$teardown_remaining" ] || continue
    teardown_status=1
    echo "test-isolation: owned $teardown_inventory remain for $teardown_project:" >&2
    printf '  %s\n' $teardown_remaining >&2
    # Names come from the label-filtered inventory above, so only this
    # project's objects are removed. Containers go first: they hold networks.
    case "$teardown_inventory" in
      # shellcheck disable=SC2086
      containers) docker rm --force --volumes $teardown_remaining >/dev/null || true ;;
      # shellcheck disable=SC2086
      networks) docker network rm $teardown_remaining >/dev/null || true ;;
      # shellcheck disable=SC2086
      volumes) docker volume rm --force $teardown_remaining >/dev/null || true ;;
    esac
  done
  if [ "$teardown_status" -ne 0 ]; then
    for teardown_inventory in containers networks volumes; do
      case "$teardown_inventory" in
        containers) teardown_remaining=$(docker ps -aq --filter "$teardown_label") ;;
        networks) teardown_remaining=$(docker network ls -q --filter "$teardown_label") ;;
        volumes) teardown_remaining=$(docker volume ls -q --filter "$teardown_label") ;;
      esac
      if [ -n "$teardown_remaining" ]; then
        echo "test-isolation: forced removal of owned $teardown_inventory failed for $teardown_project" >&2
      fi
    done
  fi
  if [ "$teardown_keep_images" = false ]; then
    remove_owned_project_images "$teardown_project"
  fi
  return "$teardown_status"
}

# build_shared_images SERVICE...
#   Builds the images of $project's `compose` for SERVICE, reusing the
#   content-hash tags shared by all checkouts and standalone suites: a hit is
#   only tagged as "$project-<service>", a miss is built and recorded. The
#   hash covers every build input (tools/testing/image_tags.py). In CI the
#   record lets the next suite of the same job reuse the image instead of
#   exporting it again (EmDash cases: 35-52 s each); inputs cannot change
#   within a job.
build_shared_images() {
  shared_config=$(mktemp) || return 1
  # The effective build sections of this suite's own Compose files.
  if ! compose config --format json >"$shared_config"; then
    rm -f "$shared_config"
    return 1
  fi
  if ! shared_plan=$(python3 "$root/tools/testing/image_tags.py" adopt \
    "$project" "$shared_config" "$@"); then
    rm -f "$shared_config"
    return 1
  fi
  shared_missing=$(printf '%s\n' "$shared_plan" | cut -d ' ' -f 1 | tr '\n' ' ')
  shared_status=0
  if [ -n "${shared_missing% }" ]; then
    # Intentional splitting of the service list.
    # shellcheck disable=SC2086
    compose build $shared_missing || shared_status=1
    if [ "$shared_status" -eq 0 ]; then
      # Recorded under the pre-build hashes, only if inputs did not change.
      # shellcheck disable=SC2046
      python3 "$root/tools/testing/image_tags.py" record "$project" "$shared_config" \
        $(printf '%s\n' "$shared_plan" | tr ' ' '=') || shared_status=1
    fi
  fi
  rm -f "$shared_config"
  return "$shared_status"
}

# remove_owned_project_images PROJECT
#   Removes the "PROJECT-<service>" images Compose built for PROJECT. An image
#   still used by a container is kept with a warning, never forced.
#   A tag named after PROJECT is also removed when another project built it:
#   the EmDash recovery targets reuse the source's image names
#   (EMDASH_RECOVERY_IMAGE_PREFIX), so a target-side build carries the
#   target's label. Tags of a project whose own name extends "PROJECT-" are
#   never touched.
remove_owned_project_images() {
  teardown_images=$(
    {
      docker image ls --filter "label=com.docker.compose.project=$1" \
        --format '{{.Repository}}:{{.Tag}}'
      docker image ls --filter "reference=$1-*" \
        --format '{{.Repository}}:{{.Tag}}'
    } | sort -u
  ) || teardown_images=""
  for teardown_image in $teardown_images; do
    case "$teardown_image" in
      "$1"-*:*) ;;
      *) continue ;;
    esac
    teardown_builder=$(docker image inspect \
      --format '{{index .Config.Labels "com.docker.compose.project"}}' \
      "$teardown_image" 2>/dev/null) || continue
    case "$teardown_builder" in
      "$1") ;;
      "$1"-*) continue ;;
    esac
    docker image rm "$teardown_image" >/dev/null 2>&1 ||
      echo "test-isolation: built image $teardown_image is still in use; kept" >&2
  done
}

# golden_seed
#   Seeds Golden Data v1 into the leaf's stack (tools/seed/golden.py seed).
#   Needs compose, $env_file, $root and the PDFs in $proof/pdfs.
golden_seed() {
  compose --profile dev-mail run --rm --user "$(id -u):$(id -g)" --no-deps \
    --env-from-file "$env_file" \
    --volume "$root:/repo:ro" \
    --volume "$proof/pdfs:/proof/pdfs:ro" \
    --entrypoint python \
    api /repo/tools/seed/golden.py seed \
    /repo/tests/fixtures/golden/v1 \
    /proof/pdfs
}
