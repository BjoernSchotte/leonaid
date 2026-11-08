#!/bin/sh
# Admin host + public host with the real services (specs/multi-domain stage
# 1, §14): the dev stack runs Caddyfile.split; the proxy answers as
# app.leonaid.test (admin) and leonaid.test (public) on the edge network.
# Core, the public app and the browsers see exactly the pilot split, with
# the dev proxy's port 8443.
#
# Usage: tools/multi_host/test.sh [root]   (heavy: run through run-in-slot.sh)
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-multi-host-test-$suffix
owned=false
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
hosts_file="$proof/compose-hosts.yml"
admin_host=app.leonaid.test
public_host=leonaid.test
admin_url="https://$admin_host:8443"
public_url="https://$public_host:8443"
# Seeded by tools/public_actions/contract.py (BROWSER_SESSIONS).
finn_session="poc070-10000000-0000-4000-8000-000000000007-browser-session-token"
anna_session="poc070-10000000-0000-4000-8000-000000000004-browser-session-token"

compose() {
  LEONAID_HTTPS_PORT=8443 \
    LEONAID_PROXY_CADDYFILE=Caddyfile.split \
    LEONAID_ADMIN_DOMAIN="$admin_host" \
    LEONAID_PUBLIC_DOMAIN="$public_host" \
    LEONAID_ADMIN_BASE_URL="$admin_url" \
    LEONAID_SITE_BASE_URL="$public_url" \
    LEONAID_PUBLIC_ORIGINS="$public_url" \
    LEONAID_ALLOWED_ORIGINS="$admin_url,https://proxy:8443" \
    docker compose \
      --project-name "$project" \
      --env-file "$env_file" \
      --file "$compose_file" \
      --file "$isolation_file" \
      --file "$hosts_file" \
      "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "multi-host-test: diagnostics for the failed real services:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=120 api public proxy >&2 || true
  fi
  if [ "$owned" = true ]; then
    if ! compose --profile dev-mail down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    if ! verify_owned_project_removed "$project"; then status=1; fi
    if [ "$status" -eq 0 ]; then echo "test-isolation: $project passed and owned resources were removed"; fi
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$env_file" ]; then
  echo "multi-host-test: ERROR: .env.local is missing; run ./leonaid bootstrap first" >&2
  exit 1
fi
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$root/tools/surveys/network_override.py" "$isolation_file"
# The default healthcheck also asks https://localhost:8443, which the split
# serves only when localhost is the public host (the README default).
cat >"$hosts_file" <<EOF
services:
  proxy:
    networks:
      edge:
        aliases: [$admin_host, $public_host]
    healthcheck:
      test:
        - CMD-SHELL
        - wget -qO- http://localhost:8080/_health && wget -qO- https://proxy:8443/_health
EOF
owned=true
# Mailpit and the worker deliver the real login mail of the magic-link proof.
compose --profile dev-mail up --build --detach --wait --wait-timeout 420 \
  proxy worker mailpit

# The proxy is healthy once `proxy` and `localhost` have certificates; the
# two test hosts may not. Caddy's startup storage clean can delete a site
# folder while its first certificate is written ("deleting site folder
# because key is empty"), and the issuance then retries after 60 s. The
# browsers start only after a TLS handshake for each test host succeeds.
tls_ready=false
attempt=0
while [ "$attempt" -lt 90 ]; do
  if compose exec -T proxy sh -ec \
    "wget -qO- https://$public_host:8443/_health && wget -qO- https://$admin_host:8443/_health" \
    >/dev/null 2>&1; then
    tls_ready=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done
[ "$tls_ready" = true ] || {
  echo "multi-host-test: ERROR: no TLS certificate for $public_host and $admin_host after 180 s" >&2
  exit 1
}
echo "multi-host-test: TLS ready for $admin_host and $public_host after $((attempt * 2)) s"

compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PYTHONPATH=/repo/src:/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/seed/golden.py seed-core \
  /repo/tests/fixtures/golden/v1
# The golden data has no member with roles in both apps: Felix Fremd (charity
# admin of another action) also acquires for Krapfentaxi here, for the
# start-area proof (specs/multi-domain §6.7).
printf '%s\n' \
  "INSERT INTO action_membership (id, action_id, user_id, role, active_from) VALUES ('21000000-0000-4000-8000-0000000000f1', '20000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000003', 'acquirer', now() - interval '1 day');" |
  compose exec -T core-postgres sh -ec \
    'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
compose run --rm --no-deps \
  --user "$(id -u):$(id -g)" \
  --env-from-file "$env_file" \
  --env API_BASE_URL=http://api:8000 \
  --env PUBLIC_BASE_URL=http://public:3000 \
  --env PYTHONPATH=/repo/src:/repo:/workspace/src \
  --volume "$root:/repo:ro" \
  --workdir /repo \
  --entrypoint python \
  api tools/public_actions/contract.py

docker run --rm \
  --network "${project}_edge" \
  --env CI=1 \
  --env HOME=/tmp \
  --env LEONAID_E2E_ADMIN_URL="$admin_url" \
  --env LEONAID_E2E_PUBLIC_URL="$public_url" \
  --env LEONAID_E2E_MAILPIT_URL=http://mailpit:8025/mail \
  --env FINN_SESSION="$finn_session" \
  --env ANNA_SESSION="$anna_session" \
  --volume "$root:/workspace:ro" \
  --volume "$proof:/proof" \
  --workdir /workspace \
  --user "$(id -u):$(id -g)" \
  "$PLAYWRIGHT_IMAGE" \
  node_modules/.bin/playwright test \
  --config=tests/e2e/public.config.mjs \
  multi-host.spec.mjs \
  --output=/proof/test-results \
  --trace=retain-on-failure \
  --reporter=line

echo "multi-host-test: OK: admin host and public host proven with the real services"
