# Sourced by the isolated auth-runtime harness (mode emdash-upgrade) before
# the stack starts. Prepares the legacy release: the last commit on main with
# EmDash 0.36.0, its locked packages and its own CMS image. The image carries
# this project's name, so the harness teardown removes it; the checkout is
# removed by the harness cleanup.
emdash_upgrade_legacy_commit=2758aba3a55774776cf14fa5359389363097e048
if ! git -C "$root" cat-file -e "$emdash_upgrade_legacy_commit^{commit}" 2>/dev/null; then
  echo "emdash-upgrade: legacy commit $emdash_upgrade_legacy_commit is missing; run: git fetch origin $emdash_upgrade_legacy_commit" >&2
  exit 1
fi
EMDASH_UPGRADE_LEGACY_ROOT=$(mktemp -d)
export EMDASH_UPGRADE_LEGACY_ROOT
git -C "$root" archive "$emdash_upgrade_legacy_commit" | tar -x -C "$EMDASH_UPGRADE_LEGACY_ROOT"
grep -q '"emdash": "0.36.0"' "$EMDASH_UPGRADE_LEGACY_ROOT/apps/campaign-site/package.json"
docker run --rm --network bridge --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e BUN_INSTALL_CACHE_DIR=/workspace/.cache/bun \
  --volume "$EMDASH_UPGRADE_LEGACY_ROOT:/workspace" --workdir /workspace \
  "$BUN_IMAGE" bun install --frozen-lockfile --ignore-scripts >/dev/null
EMDASH_UPGRADE_LEGACY_IMAGE="$project-legacy-campaign-site"
export EMDASH_UPGRADE_LEGACY_IMAGE
# --load: see release-image-identity.sh (docker-container Buildx in CI).
docker buildx build --load --tag "$EMDASH_UPGRADE_LEGACY_IMAGE" \
  --file "$EMDASH_UPGRADE_LEGACY_ROOT/infra/compose/Dockerfile.campaign-site" \
  "$EMDASH_UPGRADE_LEGACY_ROOT"
emdash_upgrade_legacy=true
echo "emdash-upgrade: legacy EmDash 0.36.0 release $emdash_upgrade_legacy_commit prepared"
