# Remove pinned images a run pulled itself, and nothing else.
# Sourced by the security gates. A pinned reference is repository:tag@digest;
# Docker stores a pull of it as repository@digest, so that exact reference is
# what is checked before the pull and removed afterwards. Images a developer
# already had (by that digest or under any tag) are never touched: removing a
# digest reference only untags it while other tags still point at the image.

# pinned_digest_ref REF: print repository@digest for repository:tag@digest.
pinned_digest_ref() {
  pinned_tagged=${1%@*}
  printf '%s@%s\n' "${pinned_tagged%:*}" "${1##*@}"
}

# pinned_image_absent REF: succeed when the exact digest is not stored locally.
pinned_image_absent() {
  ! docker image inspect "$(pinned_digest_ref "$1")" >/dev/null 2>&1
}

# remove_pulled_image REF: drop the digest reference this run pulled. A
# failure (an unrelated container started from it meanwhile) only warns.
remove_pulled_image() {
  if ! docker image rm "$(pinned_digest_ref "$1")" >/dev/null 2>&1; then
    echo "pulled-images: WARNING: could not remove $(pinned_digest_ref "$1")" >&2
  fi
}
