# Shared by standalone survey harnesses. Requires a unique $project.
# Inventory errors must never be interpreted as an unused resource name.
standalone_inventory() {
  case "$1" in
    container) docker container ls -a --format '{{.Names}}' ;;
    volume) docker volume ls --format '{{.Name}}' ;;
    network) docker network ls --format '{{.Name}}' ;;
    image) docker image ls --format '{{.Repository}}:{{.Tag}}' ;;
  esac
}
standalone_absent() {
  for resource in container volume network image; do
    if ! inventory=$(standalone_inventory "$resource"); then
      echo "Cannot read $resource inventory for $project" >&2
      return 1
    fi
    expected=$project
    [ "$resource" != image ] || expected="$project:latest"
    while IFS= read -r name; do
      if [ "$name" = "$expected" ]; then
        echo "Resource collision or cleanup residue: $resource $expected" >&2
        return 1
      fi
    done <<EOF
$inventory
EOF
  done
}
standalone_cleanup() {
  cleanup_failed=0
  if [ "$container" = true ]; then
    docker container rm -f "$project" >/dev/null || cleanup_failed=1
  fi
  if [ "$volume" = true ]; then
    docker volume rm "$project" >/dev/null || cleanup_failed=1
  fi
  if [ "$network" = true ]; then
    docker network rm "$project" >/dev/null || cleanup_failed=1
  fi
  if [ "$image" = true ]; then
    docker image rm "$project" >/dev/null || cleanup_failed=1
  fi
  standalone_absent || cleanup_failed=1
  [ "$cleanup_failed" -eq 0 ]
}
