#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project=${LEONAID_PILOT_DEPLOYMENT_PROJECT:-leonaid-pilot040-contract}
runtime_project=${LEONAID_PILOT_RUNTIME_PROJECT:-leonaid-pilot040-test}
build_project=${LEONAID_PILOT_BUILD_PROJECT:-leonaid-pilot040-release}
http_port=${LEONAID_PILOT_TEST_HTTP_PORT:-19080}
https_port=${LEONAID_PILOT_TEST_HTTPS_PORT:-19443}
workspace=$(mktemp -d)
config="$workspace/compose.json"
env_file="$workspace/production.env"
core_image="$build_project-api:latest"
web_image="$build_project-web:latest"
pwa_image="$build_project-pwa:latest"
public_image="$build_project-public:latest"

runtime_compose() {
  LEONAID_PILOT_TEST_HTTP_PORT="$http_port" \
  LEONAID_PILOT_TEST_HTTPS_PORT="$https_port" \
  LEONAID_TEST_CORE_IMAGE="$core_image" \
  LEONAID_TEST_WEB_IMAGE="$web_image" \
  LEONAID_TEST_PWA_IMAGE="$pwa_image" \
  LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
  docker compose \
    --project-name "$runtime_project" \
    --env-file "$env_file" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/pilot/compose.yml" \
    --file "$root/infra/pilot/compose.test.yml" \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "pilot-deployment-test: Diagnose der fehlgeschlagenen Services:" >&2
    runtime_compose ps >&2 || true
    runtime_compose logs --no-color --tail=80 api worker proxy >&2 || true
  fi
  runtime_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  docker image rm \
    "$core_image" "$web_image" "$pwa_image" "$public_image" \
    >/dev/null 2>&1 || true
  rm -rf "$workspace"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

cp "$root/.env.local" "$env_file"
digest=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
{
  printf '%s\n' \
    "LEONAID_ENV=production" \
    "LEONAID_SERVICE_VERSION=0.1.0" \
    "LEONAID_RELEASE_COMMIT=0123456789abcdef0123456789abcdef01234567" \
    "LEONAID_CORE_IMAGE=registry.example.org/leonaid/core@sha256:$digest" \
    "LEONAID_WEB_IMAGE=registry.example.org/leonaid/web@sha256:$digest" \
    "LEONAID_PWA_IMAGE=registry.example.org/leonaid/pwa@sha256:$digest" \
    "LEONAID_PUBLIC_IMAGE=registry.example.org/leonaid/public@sha256:$digest" \
    "LEONAID_PUBLIC_DOMAIN=portal.leonaid.org" \
    "LEONAID_PUBLIC_BASE_URL=https://portal.leonaid.org" \
    "LEONAID_ALLOWED_ORIGINS=https://portal.leonaid.org" \
    "TWENTY_PUBLIC_DOMAIN=crm.leonaid.org" \
    "TWENTY_PUBLIC_BASE_URL=https://crm.leonaid.org" \
    "CADDY_ACME_EMAIL=operations@leonaid.org" \
    "RUSTFS_BUCKET=leonaid-production-club-111" \
    "MAIL_HEALTH_URL=https://status.leonaid.org/mail" \
    "MAIL_SMTP_HOST=smtp.leonaid.org" \
    "MAIL_SMTP_PORT=587" \
    "MAIL_FROM=LeonAid <noreply@leonaid.org>" \
    "MAIL_SMTP_MODE=starttls" \
    "MAIL_SMTP_USERNAME=pilot-smtp" \
    "MAIL_SMTP_PASSWORD=pilot-smtp-password" \
    "TWENTY_INTEGRATION_API_KEY=pilot-integration-key"
} >>"$env_file"

docker compose \
  --project-name "$project" \
  --env-file "$env_file" \
  --file "$root/infra/compose/compose.yml" \
  --file "$root/infra/pilot/compose.yml" \
  config --format json >"$config"

docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_deployment/validate.py /proof/compose.json
docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_deployment/test.py /proof/compose.json

echo "pilot-deployment-test: baut vier Release-Images vor dem Deployment"
docker compose \
  --project-name "$build_project" \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
  build api web pwa public

echo "pilot-deployment-test: startet die Produktions-Topologie ohne Build"
runtime_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
runtime_compose up --detach --wait --wait-timeout 420

expected_services=$(printf '%s\n' \
  api core-postgres proxy public pwa rustfs twenty-postgres twenty-redis \
  twenty-server twenty-worker web worker | sort)
actual_services=$(runtime_compose ps --services --filter status=running | sort)
if [ "$actual_services" != "$expected_services" ]; then
  echo "pilot-deployment-test: ERROR: Pilot-Core ist nicht vollständig aktiv" >&2
  exit 1
fi

for service in $expected_services; do
  container_id=$(runtime_compose ps --quiet "$service")
  health=$(docker inspect --format '{{.State.Health.Status}}' "$container_id")
  if [ "$health" != "healthy" ]; then
    echo "pilot-deployment-test: ERROR: $service ist $health" >&2
    exit 1
  fi
done

base_url="portal.leonaid.org"
crm_url="crm.leonaid.org"
curl --fail --silent --insecure \
  --resolve "$base_url:$https_port:127.0.0.1" \
  "https://$base_url:$https_port/_health" | grep -q "ready"
curl --fail --silent --insecure \
  --resolve "$base_url:$https_port:127.0.0.1" \
  "https://$base_url:$https_port/admin/" | grep -q "Charity-Aktionen"
curl --fail --silent --insecure \
  --resolve "$base_url:$https_port:127.0.0.1" \
  "https://$base_url:$https_port/api/health/ready" | grep -q '"status"'
curl --fail --silent --insecure \
  --resolve "$crm_url:$https_port:127.0.0.1" \
  "https://$crm_url:$https_port/healthz" | grep -q '"status":"ok"'

echo "pilot-deployment-test: OK: Contract und produktionsähnlicher Leerstart bewiesen"
