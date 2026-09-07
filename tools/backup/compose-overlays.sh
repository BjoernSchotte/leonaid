#!/bin/sh
# Sourced by backup/restore. Input is a repository-owned list of relative
# Compose paths, never rendered configuration or shell commands.
validate_recovery_overlays() {
  [ -n "$recovery_overlay_list" ] || return 0
  [ -z "$compose_overlay" ] && [ -z "$compose_overlay_secondary" ] ||
    fail "Compose-Dateiliste darf nicht mit einzelnen Overlays kombiniert werden"
  case "$recovery_overlay_list" in
    "$root"/*) ;;
    *) fail "Compose-Dateiliste muss im Repository liegen" ;;
  esac
  [ -f "$recovery_overlay_list" ] && [ ! -L "$recovery_overlay_list" ] ||
    fail "Compose-Dateiliste fehlt oder ist ein Symlink"
  list_directory=$(cd "$(dirname "$recovery_overlay_list")" && pwd -P)
  case "$list_directory/" in "$root/"*) ;; *) fail "Compose-Dateiliste verlässt das Repository" ;; esac
  count=0
  while IFS= read -r relative || [ -n "$relative" ]; do
    case "$relative" in
      ''|*[!a-zA-Z0-9_./-]*|/*|*..*) fail "Ungültiger Compose-Dateipfad" ;;
    esac
    case "$relative" in *.yml|*.yaml) ;; *) fail "Compose-Dateipfad benötigt YAML-Endung" ;; esac
    [ -f "$root/$relative" ] && [ ! -L "$root/$relative" ] || fail "Compose-Datei fehlt oder ist ein Symlink"
    physical=$(cd "$(dirname "$root/$relative")" && pwd -P)
    case "$physical/" in "$root/"*) ;; *) fail "Compose-Dateipfad verlässt das Repository" ;; esac
    count=$((count + 1))
    [ "$count" -le 16 ] || fail "Zu viele Compose-Dateien"
  done < "$recovery_overlay_list"
  [ "$count" -gt 0 ] || fail "Compose-Dateiliste ist leer"
}
