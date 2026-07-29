#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project=${LEONAID_PILOT_DEPLOYMENT_PROJECT:-leonaid-production-test}
runtime_project=${LEONAID_PILOT_RUNTIME_PROJECT:-leonaid-pilot040-test}
build_project=${LEONAID_PILOT_BUILD_PROJECT:-leonaid-pilot040-release}
http_port=${LEONAID_PILOT_TEST_HTTP_PORT:-19080}
https_port=${LEONAID_PILOT_TEST_HTTPS_PORT:-19443}
workspace=$(mktemp -d)
config="$workspace/compose.json"
env_file="$workspace/production.env"
backup_manifest="$workspace/backup-manifest.json"
ca_file="$workspace/caddy-root.crt"
alert_webhook_file="$workspace/alert-webhook-url"
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
printf '%s\n' "https://alerts.leonaid.org/pilot" >"$alert_webhook_file"
chmod 600 "$alert_webhook_file"
digest=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
{
  printf '%s\n' \
    "LEONAID_ENV=production" \
    "LEONAID_DEPLOYMENT_STAGE=production" \
    "LEONAID_COMPOSE_PROJECT=$project" \
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
    "MAIL_HEALTH_URL=https://portal.leonaid.org/_health" \
    "MAIL_SMTP_HOST=smtp.leonaid.org" \
    "MAIL_SMTP_PORT=587" \
    "MAIL_FROM=LeonAid <noreply@leonaid.org>" \
    "MAIL_ENVELOPE_FROM=bounces@leonaid.org" \
    "MAIL_REPLY_TO=support@leonaid.org" \
    "MAIL_SMTP_MODE=starttls" \
    "MAIL_SMTP_USERNAME=pilot-smtp" \
    "RESTIC_REPOSITORY=s3:https://backup.leonaid.org/production-test" \
    "LEONAID_BACKUP_MANIFEST_PATH=$backup_manifest" \
    "LEONAID_MONITORED_DISK_PATH=$workspace" \
    "LEONAID_ALERT_WEBHOOK_URL_FILE=$alert_webhook_file" \
    "CORE_POSTGRES_PASSWORD=core-postgres-production-test-001" \
    "LEONAID_SECRET_KEY=leonaid-application-production-test-002" \
    "LEONAID_SESSION_ENCRYPTION_KEY=leonaid-session-production-test-003" \
    "MAIL_SMTP_PASSWORD=leonaid-smtp-production-test-004" \
    "RUSTFS_ACCESS_KEY=leonaid-rustfs-access-production-test-005" \
    "RUSTFS_SECRET_KEY=leonaid-rustfs-secret-production-test-006" \
    "TWENTY_ACCESS_TOKEN_SECRET=twenty-access-production-test-007" \
    "TWENTY_INTEGRATION_API_KEY=twenty-integration-production-test-008" \
    "TWENTY_LOGIN_TOKEN_SECRET=twenty-login-production-test-009"
} >>"$env_file"
chmod 600 "$env_file"

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
  --volume "$workspace:$workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_deployment/validate.py /proof/compose.json
docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof:ro" \
  --volume "$workspace:$workspace:ro" \
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

proxy_id=$(runtime_compose ps --quiet proxy)
runtime_compose exec --no-TTY proxy \
  cat /data/caddy/pki/authorities/local/root.crt >"$ca_file"
chmod 600 "$ca_file"
docker run --rm \
  --env "BACKUP_SOURCE_PROJECT=$project" \
  --volume "$workspace:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import datetime,json,os,pathlib
pathlib.Path("/proof/backup-manifest.json").write_text(json.dumps({
  "schemaVersion":1,
  "createdAt":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "sourceProject":os.environ["BACKUP_SOURCE_PROJECT"],
  "files":{"core.dump":{"sha256":"a"*64,"size":1}}
},sort_keys=True)+"\n",encoding="utf-8")'

docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof:ro" \
  --volume "$workspace:$workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_deployment/doctor_test.py \
    /workspace \
    /proof/production.env \
    /proof/compose.json \
    /proof/backup-manifest.json \
    0123456789abcdef0123456789abcdef01234567

echo "pilot-deployment-test: prüft den Deployment Doctor gegen reale TLS-Dienste"
docker run --rm \
  --network "container:$proxy_id" \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof:ro" \
  --volume "$workspace:$workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_deployment/doctor.py /workspace \
    --env-file /proof/production.env \
    --compose-config /proof/compose.json \
    --backup-manifest /proof/backup-manifest.json \
    --expected-release-commit 0123456789abcdef0123456789abcdef01234567 \
    --deployment-only \
    --ca-file /proof/caddy-root.crt \
    --resolve portal.leonaid.org=127.0.0.1:443 \
    --resolve crm.leonaid.org=127.0.0.1:443 \
    --disk-path /proof \
    --minimum-free-bytes 1048576 \
    --minimum-certificate-validity-hours 1

unsafe_env="$workspace/unsafe.env"
cp "$env_file" "$unsafe_env"
sentinel=__THIS_SECRET_MUST_NEVER_APPEAR_123456789__
printf '%s\n' "LEONAID_SECRET_KEY=$sentinel" >>"$unsafe_env"
chmod 600 "$unsafe_env"
set +e
unsafe_output=$(docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof:ro" \
  --volume "$workspace:$workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_deployment/doctor.py /workspace \
    --env-file /proof/unsafe.env \
    --compose-config /proof/compose.json \
    --backup-manifest /proof/backup-manifest.json \
    --expected-release-commit 0123456789abcdef0123456789abcdef01234567 \
    --deployment-only 2>&1)
unsafe_status=$?
set -e
if [ "$unsafe_status" -eq 0 ]; then
  echo "pilot-deployment-test: ERROR: unsicheres Secret wurde akzeptiert" >&2
  exit 1
fi
if printf '%s' "$unsafe_output" | grep -q "$sentinel"; then
  echo "pilot-deployment-test: ERROR: Doctor hat ein Secret ausgegeben" >&2
  exit 1
fi
if ! printf '%s' "$unsafe_output" | grep -q "secret_invalid:LEONAID_SECRET_KEY"; then
  echo "pilot-deployment-test: ERROR: Secret-Fehler ist nicht diagnostizierbar" >&2
  exit 1
fi

echo "pilot-deployment-test: OK: Contract, Leerstart und realer Deployment Doctor bewiesen"
