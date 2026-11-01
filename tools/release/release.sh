#!/bin/sh
# Cut a LeonAid release: ./leonaid release [--dry-run] [--no-ci-check]
#   on main               -> vYYYY.M.N   (N counts releases within the UTC month)
#   on release/YYYY.M.N   -> vYYYY.M.N.P (fix release on top of vYYYY.M.N)
#
# Requires a clean tree whose HEAD is pushed and green in CI. Sets an annotated
# tag with notes from the Conventional Commits and pushes it. The tag starts
# .github/workflows/release.yml, which builds and pushes the release images
# and publishes the GitHub release with the image references and manifest.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$(git rev-parse --show-toplevel)"
. "$here/release-lib.sh"
die() {
  echo "release: $*" >&2
  exit 1
}

dry=0
ci_check=1
for argument in "$@"; do
  case $argument in
    --dry-run) dry=1 ;;
    --no-ci-check) ci_check=0 ;;
    *)
      echo "usage: ./leonaid release [--dry-run] [--no-ci-check]" >&2
      exit 2
      ;;
  esac
done

branch=$(git symbolic-ref --short -q HEAD) || die "detached HEAD"
[ -z "$(git status --porcelain)" ] || die "uncommitted changes"
git fetch -q --tags origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse -q --verify "origin/$branch" || true)" ] ||
  die "HEAD is not origin/$branch (push or pull first)"
case $branch in
  main) version=$(next_version) ;;
  release/*)
    base=${branch#release/}
    echo "$base" | grep -Eq "$_base_re" || die "releases come from main or release/YYYY.M.N, not $branch"
    git merge-base --is-ancestor "v$base" HEAD 2>/dev/null || die "v$base is not in this branch"
    version=$(next_fix "$base")
    ;;
  *) die "releases come from main or release/YYYY.M.N, not $branch" ;;
esac

# All check runs on the commit finished and none failed. RELEASE_CI_STATE
# replaces the GitHub query in tests.
ci_state() {
  if [ -n "${RELEASE_CI_STATE:-}" ]; then
    echo "$RELEASE_CI_STATE"
    return
  fi
  gh api "repos/{owner}/{repo}/commits/$1/check-runs?per_page=100" --paginate \
    --jq '.check_runs[] | "\(.status) \(.conclusion)"' |
    awk '
      $1 != "completed" { pending++ ; next }
      $2 != "success" && $2 != "skipped" && $2 != "neutral" { failed++ }
      { total++ }
      END {
        if (failed) print "failed"
        else if (pending) print "pending"
        else if (!total) print "none"
        else print "green"
      }'
}

require_green_ci() {
  [ "$ci_check" = 1 ] || return 0
  state=$(ci_state "$1") || die "cannot read the CI state of $1"
  case $state in
    green) ;;
    pending) die "CI still runs on $1; wait for it" ;;
    none) die "no CI checks found on $1" ;;
    *) die "CI failed on $1; fix it before releasing" ;;
  esac
}

start_release_workflow() {
  if [ -n "${RELEASE_WORKFLOW_COMMAND:-}" ]; then
    $RELEASE_WORKFLOW_COMMAND "$1"
    return
  fi
  gh workflow run release.yml --ref "$1"
}

# Resume: a release tag on HEAD means an earlier run stopped after tagging.
# Push the tag again (a no-op when present) and start the release workflow if
# the GitHub release is still missing. Never set a new tag here.
done_tag=$(git tag --points-at HEAD | grep -E "$_release_re|$_fix_re" | sort_versions | tail -1 || true)
case $branch in
  release/*)
    [ "$done_tag" != "v$base" ] ||
      die "nothing to release: no commit since v$base on $branch"
    ;;
esac
if [ -n "$done_tag" ]; then
  echo "LeonAid ${done_tag#v} is tagged already: resuming"
  [ "$dry" = 0 ] || exit 0
  gh auth status >/dev/null 2>&1 || die "gh is not logged in"
  git push -q origin "$done_tag"
  if gh release view "$done_tag" >/dev/null 2>&1; then
    echo "release: GitHub release $done_tag exists; nothing to do"
    exit 0
  fi
  start_release_workflow "$done_tag"
  echo "release: started the release workflow for $done_tag"
  exit 0
fi

previous=$(last_tag HEAD)
notes=$(release_notes "$previous" HEAD)
echo "LeonAid $version (since ${previous:-the beginning})"
printf '%s\n' "$notes"
[ "$dry" = 0 ] || exit 0

gh auth status >/dev/null 2>&1 || die "gh is not logged in"
require_green_ci "$(git rev-parse HEAD)"
# verbatim: the default cleanup would drop the "### " headings of the notes.
git tag -a --cleanup=verbatim "v$version" -m "LeonAid $version" -m "$notes"
git push -q origin "v$version"
echo "release: pushed v$version; the release workflow builds the images now"
echo "release: follow it with: gh run list --workflow release.yml --limit 1"
