#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
. "$root/infra/locks/images.env"

docker run --rm \
  --volume "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/ci/no_test_doubles_test.py /workspace
docker run --rm \
  --volume "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/ci/workflow_contract_test.py /workspace
docker run --rm \
  --volume "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/ci/sanitize_artifacts_test.py /workspace
/bin/sh "$root/tools/pilot/test.sh" "$root"
docker run --rm \
  --volume "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  /bin/sh /workspace/tools/pins/test.sh /workspace
docker run --rm \
  --volume "$root:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/schema/check_migrations.py \
  /workspace/migrations/versions

if git -C "$root" ls-files | grep -E '(^|/)(\\.env\\.local|sessions?\\.env)$'; then
  echo "ci-security: ERROR: lokale Secrets oder Sitzungen sind versioniert" >&2
  exit 1
fi

docker run --rm \
  --volume "$root:/workspace:ro" \
  --volume leonaid-trivy-cache:/root/.cache/trivy \
  "$TRIVY_IMAGE" \
  filesystem \
  --scanners secret \
  --exit-code 1 \
  --skip-dirs /workspace/.artifacts \
  --skip-dirs /workspace/.cache \
  --skip-dirs /workspace/.git \
  --skip-dirs /workspace/.local \
  --skip-dirs /workspace/node_modules \
  --skip-files /workspace/.env.local \
  /workspace

docker run --rm \
  --volume "$root:/workspace:ro" \
  --volume leonaid-trivy-cache:/root/.cache/trivy \
  "$TRIVY_IMAGE" \
  filesystem \
  --scanners vuln \
  --severity CRITICAL \
  --exit-code 1 \
  /workspace

docker compose \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
  build api worker web pwa public

for image_name in \
  leonaid-api:latest \
  leonaid-worker:latest \
  leonaid-web:latest \
  leonaid-pwa:latest \
  leonaid-public:latest; do
  docker run --rm \
    --volume /var/run/docker.sock:/var/run/docker.sock \
    --volume leonaid-trivy-cache:/root/.cache/trivy \
    "$TRIVY_IMAGE" \
    image \
    --scanners vuln \
    --severity CRITICAL \
    --ignore-unfixed \
    --exit-code 1 \
    "$image_name"
done

docker run --rm \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume leonaid-trivy-cache:/root/.cache/trivy \
  "$TRIVY_IMAGE" \
  image \
  --scanners vuln \
  --severity CRITICAL \
  --ignore-unfixed \
  --exit-code 1 \
  "$CADDY_IMAGE"

/bin/sh "$root/tools/security/test.sh" "$root"

echo "ci-security: OK: Policies, Secrets und kritische Abhängigkeiten/Images"
