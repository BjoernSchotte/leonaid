# Sourced by ./leonaid (pilot_backup_topology) and tools/backup/backup.sh.
# cms_bootstrap_state VOLUME prints "complete" when the CMS setup of that
# bootstrap-state volume is complete and "unfinished" when it provably is
# not: no volume or no state.json (setup never armed) or a state other than
# complete. Anything that cannot be read (Docker error, unreadable or
# malformed file) returns 1 and prints nothing: a live CMS must never fall
# back to a backup without its data because a probe failed.
# Needs ALPINE_IMAGE (infra/locks/images.env).
cms_bootstrap_state() {
  cms_state_volume=$1
  cms_state_listed=$(docker volume ls --quiet --filter "name=^${cms_state_volume}\$") ||
    return 1
  if [ -z "$cms_state_listed" ]; then
    echo unfinished
    return 0
  fi
  # A probe that does not run (pull, daemon, mount) exits non-zero; an absent
  # file is reported explicitly, so the two never look alike.
  cms_state_content=$(docker run --rm --network none \
    --volume "${cms_state_volume}:/state:ro" "$ALPINE_IMAGE" \
    sh -c 'if [ ! -e /state/state.json ]; then echo ABSENT; else cat /state/state.json; fi') ||
    return 1
  case "$cms_state_content" in
    ABSENT) echo unfinished ;;
    *'"status":"complete"'*) echo complete ;;
    *'"status":"armed"'*|*'"status":"consumed"'*) echo unfinished ;;
    *) return 1 ;;
  esac
}
