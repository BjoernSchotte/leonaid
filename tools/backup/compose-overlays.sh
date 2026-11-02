#!/bin/sh
# Sourced by backup/restore. Input is a repository-owned list of relative
# Compose paths, never rendered configuration or shell commands.
validate_recovery_overlays() {
  [ -n "$recovery_overlay_list" ] || return 0
  [ -z "$compose_overlay" ] && [ -z "$compose_overlay_secondary" ] ||
    fail "Compose file list must not be combined with single overlays"
  case "$recovery_overlay_list" in
    "$root"/*) ;;
    *) fail "Compose file list must be inside the repository" ;;
  esac
  [ -f "$recovery_overlay_list" ] && [ ! -L "$recovery_overlay_list" ] ||
    fail "Compose file list missing or is a symlink"
  list_directory=$(cd "$(dirname "$recovery_overlay_list")" && pwd -P)
  case "$list_directory/" in "$root/"*) ;; *) fail "Compose file list leaves the repository" ;; esac
  count=0
  while IFS= read -r relative || [ -n "$relative" ]; do
    case "$relative" in
      ''|*[!a-zA-Z0-9_./-]*|/*|*..*) fail "invalid Compose file path" ;;
    esac
    case "$relative" in *.yml|*.yaml) ;; *) fail "Compose file path requires a YAML extension" ;; esac
    [ -f "$root/$relative" ] && [ ! -L "$root/$relative" ] || fail "Compose file missing or is a symlink"
    physical=$(cd "$(dirname "$root/$relative")" && pwd -P)
    case "$physical/" in "$root/"*) ;; *) fail "Compose file path leaves the repository" ;; esac
    count=$((count + 1))
    [ "$count" -le 16 ] || fail "too many Compose files"
  done < "$recovery_overlay_list"
  [ "$count" -gt 0 ] || fail "Compose file list is empty"
}
