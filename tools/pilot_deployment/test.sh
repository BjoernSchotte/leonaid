#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project=${LEONAID_PILOT_DEPLOYMENT_PROJECT:-leonaid-pilot040-contract}
workspace=$(mktemp -d)
config="$workspace/compose.json"
env_file="$workspace/production.env"

cleanup() {
  status=$?
  rm -rf "$workspace"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

cp "$root/.env.local" "$env_file"
digest=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
{
  printf '%s\n' \
    "LEONAID_ENV=production" \
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

echo "pilot-deployment-test: OK: Docker Compose wurde real zusammengeführt und fail-closed geprüft"
