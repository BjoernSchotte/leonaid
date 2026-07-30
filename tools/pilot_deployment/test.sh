#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
project=${LEONAID_PILOT_DEPLOYMENT_PROJECT:-leonaid-production-test}
runtime_project=${LEONAID_PILOT_RUNTIME_PROJECT:-$project}
build_project=${LEONAID_PILOT_BUILD_PROJECT:-leonaid-pilot040-release}
http_port=${LEONAID_PILOT_TEST_HTTP_PORT:-19080}
https_port=${LEONAID_PILOT_TEST_HTTPS_PORT:-19443}
restore_http_port=${LEONAID_PILOT_RESTORE_TEST_HTTP_PORT:-19081}
restore_https_port=${LEONAID_PILOT_RESTORE_TEST_HTTPS_PORT:-19444}
workspace=$(mktemp -d)
manifest_proof_directory=$(mktemp -d)
config="$workspace/compose.json"
env_file="$workspace/production.env"
backup_manifest="$workspace/backup-manifest.json"
release_manifest="$workspace/release-manifest.json"
release_ledger="$workspace/release-ledger.jsonl"
drifted_release_manifest="$workspace/drifted-release-manifest.json"
accepted_decisions="$workspace/accepted-decisions.md"
target_env_file="$workspace/restore.env"
restic_password_file="$workspace/restic-password"
wrong_restic_password_file="$workspace/wrong-restic-password"
backup_credentials_file="$workspace/backup-s3.env"
ca_file="$workspace/caddy-root.crt"
alert_webhook_file="$workspace/alert-webhook-url"
operator_backup_project=leonaid-pilot-operator-backup
operator_backup_container="$operator_backup_project-rustfs"
operator_backup_volume="$operator_backup_project-rustfs-data"
operator_backup_bucket=leonaid-pilot-operator
restore_project=leonaid-restore-pilot-operator
core_image_tag="$build_project-api:latest"
web_image_tag="$build_project-web:latest"
pwa_image_tag="$build_project-pwa:latest"
public_image_tag="$build_project-public:latest"
core_image="$core_image_tag"
web_image="$web_image_tag"
pwa_image="$pwa_image_tag"
public_image="$public_image_tag"
release_commit=$(git -C "$root" rev-parse HEAD)

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

restore_compose() {
  LEONAID_PILOT_TEST_HTTP_PORT="$restore_http_port" \
  LEONAID_PILOT_TEST_HTTPS_PORT="$restore_https_port" \
  LEONAID_TEST_CORE_IMAGE="$core_image" \
  LEONAID_TEST_WEB_IMAGE="$web_image" \
  LEONAID_TEST_PWA_IMAGE="$pwa_image" \
  LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
  docker compose \
    --project-name "$restore_project" \
    --env-file "$target_env_file" \
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
    if [ -f "$backup_manifest" ]; then
      docker run --rm \
        --volume "$backup_manifest:/proof/manifest.json:ro" \
        "$PYTHON_IMAGE" \
        python -c 'import hashlib,json,pathlib
p=pathlib.Path("/proof/manifest.json")
data=p.read_bytes()
try:
    value=json.loads(data)
    result="valid" if isinstance(value,dict) else "not-object"
except (UnicodeDecodeError,json.JSONDecodeError):
    result="invalid-json"
print(
    "pilot-deployment-test: backup-manifest "
    f"bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()} json={result}"
)' >&2 || true
    fi
  fi
  runtime_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  restore_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  docker rm --force "$operator_backup_container" >/dev/null 2>&1 || true
  docker volume rm "$operator_backup_volume" >/dev/null 2>&1 || true
  docker image rm \
    "$core_image_tag" "$web_image_tag" "$pwa_image_tag" "$public_image_tag" \
    >/dev/null 2>&1 || true
  rm -rf "$manifest_proof_directory"
  rm -rf "$workspace"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

docker rm --force "$operator_backup_container" >/dev/null 2>&1 || true
docker volume rm "$operator_backup_volume" >/dev/null 2>&1 || true
docker volume create \
  --label "com.docker.compose.project=$operator_backup_project" \
  "$operator_backup_volume" >/dev/null
backup_access_key=pilot-operator-backup-access-001
backup_secret_key=pilot-operator-backup-secret-002
docker run --detach \
  --name "$operator_backup_container" \
  --label "com.docker.compose.project=$operator_backup_project" \
  --env "RUSTFS_ACCESS_KEY=$backup_access_key" \
  --env "RUSTFS_SECRET_KEY=$backup_secret_key" \
  --volume "$operator_backup_volume:/data" \
  --health-cmd 'curl --fail http://localhost:9000/health' \
  --health-interval 2s \
  --health-timeout 2s \
  --health-retries 30 \
  "$RUSTFS_IMAGE" /data >/dev/null
attempts=0
while [ "$attempts" -lt 60 ]; do
  backup_health=$(
    docker inspect --format '{{.State.Health.Status}}' \
      "$operator_backup_container" 2>/dev/null || true
  )
  [ "$backup_health" = "healthy" ] && break
  attempts=$((attempts + 1))
  sleep 1
done
[ "$backup_health" = "healthy" ] || {
  echo "pilot-deployment-test: ERROR: Operator-Backupziel wurde nicht bereit" >&2
  exit 1
}
backup_ip=$(
  docker inspect \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
    "$operator_backup_container"
)
[ -n "$backup_ip" ] || {
  echo "pilot-deployment-test: ERROR: Operator-Backupziel hat keine IP" >&2
  exit 1
}
backup_repository="s3:http://$backup_ip:9000/$operator_backup_bucket"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$workspace:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import pathlib,secrets
pathlib.Path("/proof/restic-password").write_text(secrets.token_urlsafe(48)+"\n")
pathlib.Path("/proof/wrong-restic-password").write_text("too-short\n")
pathlib.Path("/proof/backup-s3.env").write_text(
  "AWS_ACCESS_KEY_ID=pilot-operator-backup-access-001\n"
  "AWS_SECRET_ACCESS_KEY=pilot-operator-backup-secret-002\n"
  "AWS_DEFAULT_REGION=us-east-1\n"
  "AWS_REGION=us-east-1\n"
)'
chmod 600 \
  "$restic_password_file" \
  "$wrong_restic_password_file" \
  "$backup_credentials_file"
docker run --rm \
  --env "AWS_ACCESS_KEY_ID=$backup_access_key" \
  --env "AWS_SECRET_ACCESS_KEY=$backup_secret_key" \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  /workspace/.venv/bin/python -c "import boto3
s3=boto3.client(
  's3',
  endpoint_url='http://$backup_ip:9000',
  aws_access_key_id='$backup_access_key',
  aws_secret_access_key='$backup_secret_key',
  region_name='us-east-1',
)
s3.create_bucket(Bucket='$operator_backup_bucket')"

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
    "LEONAID_RELEASE_COMMIT=$release_commit" \
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
    "RESTIC_REPOSITORY=$backup_repository" \
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
    "$release_commit"

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
    --expected-release-commit "$release_commit" \
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
    --expected-release-commit "$release_commit" \
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

echo "pilot-deployment-test: beweist den manifestgebundenen Operator-Deploy"
core_image=$(docker image inspect --format '{{.Id}}' "$core_image_tag")
web_image=$(docker image inspect --format '{{.Id}}' "$web_image_tag")
pwa_image=$(docker image inspect --format '{{.Id}}' "$pwa_image_tag")
public_image=$(docker image inspect --format '{{.Id}}' "$public_image_tag")
runtime_compose config --format json >"$config"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_release/manifest.py create \
    --root /workspace \
    --release-id pilot-deploy-test \
    --version 0.1.0-test \
    --git-commit "$release_commit" \
    --deployment-mode test \
    --compose-config /proof/compose.json \
    --output /proof/release-manifest.json
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import pathlib
source=pathlib.Path("/workspace/specs/leonaid-pilot/DECISIONS.md")
target=pathlib.Path("/proof/accepted-decisions.md")
lines=[]
for line in source.read_text(encoding="utf-8").splitlines():
    if line.startswith("| PILOT-"):
        cells=[cell.strip() for cell in line.strip().strip("|").split("|")]
        decision_id=cells[0]
        cells[6]="EVID-TEST-"+decision_id.removeprefix("PILOT-")
        cells[7]="accepted"
        cells[8]=(
            "small_business" if decision_id=="PILOT-TAX-001"
            else "not_required" if decision_id=="PILOT-INV-002"
            else "confirmed"
        )
        line="| "+" | ".join(cells)+" |"
    lines.append(line)
target.write_text("\n".join(lines)+"\n",encoding="utf-8")
target.chmod(0o600)'
cp "$release_manifest" "$drifted_release_manifest"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$workspace:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import json,pathlib
p=pathlib.Path("/proof/drifted-release-manifest.json")
value=json.loads(p.read_text(encoding="utf-8"))
value["images"]["api"]="sha256:"+"b"*64
p.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")'
set +e
drift_output=$(
  LEONAID_PILOT_TEST_COMPOSE_OVERLAY="$root/infra/pilot/compose.test.yml" \
    LEONAID_PILOT_TEST_DECISIONS_FILE="$accepted_decisions" \
    LEONAID_TEST_CORE_IMAGE="$core_image" \
    LEONAID_TEST_WEB_IMAGE="$web_image" \
    LEONAID_TEST_PWA_IMAGE="$pwa_image" \
    LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
    "$root/leonaid" pilot-deploy \
      --env-file "$env_file" \
      --backup-manifest "$backup_manifest" \
      --release-manifest "$drifted_release_manifest" 2>&1
)
drift_status=$?
set -e
if [ "$drift_status" -eq 0 ]; then
  echo "pilot-deployment-test: ERROR: Manifest-/Compose-Drift wurde deployed" >&2
  exit 1
fi
if ! printf '%s' "$drift_output" |
  grep -Fq "Manifest-Images weichen"; then
  echo "pilot-deployment-test: ERROR: Manifest-Drift ist nicht diagnostizierbar" >&2
  exit 1
fi
LEONAID_PILOT_TEST_COMPOSE_OVERLAY="$root/infra/pilot/compose.test.yml" \
  LEONAID_PILOT_TEST_DECISIONS_FILE="$accepted_decisions" \
  LEONAID_PILOT_TEST_DOCTOR_NETWORK="container:$proxy_id" \
  LEONAID_PILOT_TEST_CA_FILE="$ca_file" \
  LEONAID_TEST_CORE_IMAGE="$core_image" \
  LEONAID_TEST_WEB_IMAGE="$web_image" \
  LEONAID_TEST_PWA_IMAGE="$pwa_image" \
  LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
  "$root/leonaid" pilot-deploy \
    --env-file "$env_file" \
    --backup-manifest "$backup_manifest" \
    --release-manifest "$release_manifest"

echo "pilot-deployment-test: beweist Operator-Backup und buildfreien Restore"
runtime_compose exec -T core-postgres psql \
  --username "${CORE_POSTGRES_USER:-leonaid}" \
  --dbname "${CORE_POSTGRES_DB:-leonaid}" \
  --command "CREATE TABLE pilot_operator_probe (value text NOT NULL); INSERT INTO pilot_operator_probe VALUES ('core-operator-backup');"
runtime_compose exec -T twenty-postgres psql \
  --username "${TWENTY_POSTGRES_USER:-twenty}" \
  --dbname "${TWENTY_POSTGRES_DB:-default}" \
  --command "CREATE TABLE public.pilot_operator_probe (value text NOT NULL); INSERT INTO public.pilot_operator_probe VALUES ('twenty-operator-backup');"
docker run --rm \
  --volume "${project}_rustfs-data:/data" \
  "$ALPINE_IMAGE" \
  sh -eu -c 'printf "%s\n" "rustfs-operator-backup" > /data/pilot-operator-probe'
docker run --rm \
  --volume "${project}_twenty-server-data:/data" \
  "$ALPINE_IMAGE" \
  sh -eu -c 'printf "%s\n" "twenty-storage-operator-backup" > /data/pilot-operator-probe'
set +e
wrong_backup_output=$(
  LEONAID_PILOT_TEST_COMPOSE_OVERLAY="$root/infra/pilot/compose.test.yml" \
    LEONAID_PILOT_TEST_DECISIONS_FILE="$accepted_decisions" \
    LEONAID_PILOT_TEST_DOCTOR_NETWORK="container:$proxy_id" \
    LEONAID_PILOT_TEST_CA_FILE="$ca_file" \
    LEONAID_TEST_CORE_IMAGE="$core_image" \
    LEONAID_TEST_WEB_IMAGE="$web_image" \
    LEONAID_TEST_PWA_IMAGE="$pwa_image" \
    LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
    "$root/leonaid" pilot-backup \
      --env-file "$env_file" \
      --backup-manifest "$backup_manifest" \
      --password-file "$wrong_restic_password_file" \
      --credentials-file "$backup_credentials_file" 2>&1
)
wrong_backup_status=$?
set -e
if [ "$wrong_backup_status" -eq 0 ]; then
  echo "pilot-deployment-test: ERROR: zu kurzes Restic-Passwort wurde akzeptiert" >&2
  exit 1
fi
if ! printf '%s' "$wrong_backup_output" |
  grep -Fq "Restic-Passwort muss mindestens 24 Zeichen"; then
  echo "pilot-deployment-test: ERROR: Passwortablehnung ist nicht diagnostizierbar" >&2
  exit 1
fi

echo "pilot-deployment-test: beweist den vollständigen Operator-Release"
set +e
missing_staging_output=$(
  LEONAID_PILOT_TEST_COMPOSE_OVERLAY="$root/infra/pilot/compose.test.yml" \
    LEONAID_PILOT_TEST_DECISIONS_FILE="$accepted_decisions" \
    LEONAID_PILOT_TEST_DOCTOR_NETWORK="container:$proxy_id" \
    LEONAID_PILOT_TEST_CA_FILE="$ca_file" \
    LEONAID_TEST_CORE_IMAGE="$core_image" \
    LEONAID_TEST_WEB_IMAGE="$web_image" \
    LEONAID_TEST_PWA_IMAGE="$pwa_image" \
    LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
    "$root/leonaid" pilot-release \
      --env-file "$env_file" \
      --backup-manifest "$backup_manifest" \
      --release-manifest "$release_manifest" \
      --ledger "$release_ledger" \
      --password-file "$restic_password_file" \
      --credentials-file "$backup_credentials_file" \
      --evidence-id PILOT-043-OPERATOR-NEGATIVE \
      --occurred-at 2026-07-30T12:00:00Z 2>&1
)
missing_staging_status=$?
set -e
if [ "$missing_staging_status" -eq 0 ]; then
  echo "pilot-deployment-test: ERROR: Produktion ohne Staging-Promotion wurde akzeptiert" >&2
  exit 1
fi
if ! printf '%s' "$missing_staging_output" |
  grep -Fq "Produktion erfordert dasselbe in Staging verifizierte Manifest"; then
  echo "pilot-deployment-test: ERROR: fehlende Staging-Promotion ist nicht diagnostizierbar" >&2
  exit 1
fi
[ ! -e "$release_ledger" ] || {
  echo "pilot-deployment-test: ERROR: abgelehnter Release hat das Ledger verändert" >&2
  exit 1
}
"$root/leonaid" pilot-release-record \
  --manifest "$release_manifest" \
  --ledger "$release_ledger" \
  --event staging_started \
  --result passed \
  --evidence-id PILOT-043-STAGING-OPERATOR \
  --occurred-at 2026-07-30T12:01:00Z
"$root/leonaid" pilot-release-record \
  --manifest "$release_manifest" \
  --ledger "$release_ledger" \
  --event staging_verified \
  --result passed \
  --evidence-id PILOT-043-STAGING-OPERATOR \
  --occurred-at 2026-07-30T12:02:00Z
LEONAID_PILOT_TEST_COMPOSE_OVERLAY="$root/infra/pilot/compose.test.yml" \
  LEONAID_PILOT_TEST_DECISIONS_FILE="$accepted_decisions" \
  LEONAID_PILOT_TEST_DOCTOR_NETWORK="container:$proxy_id" \
  LEONAID_PILOT_TEST_CA_FILE="$ca_file" \
  LEONAID_TEST_CORE_IMAGE="$core_image" \
  LEONAID_TEST_WEB_IMAGE="$web_image" \
  LEONAID_TEST_PWA_IMAGE="$pwa_image" \
  LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
  "$root/leonaid" pilot-release \
    --env-file "$env_file" \
    --backup-manifest "$backup_manifest" \
    --release-manifest "$release_manifest" \
    --ledger "$release_ledger" \
    --password-file "$restic_password_file" \
    --credentials-file "$backup_credentials_file" \
    --evidence-id PILOT-043-PRODUCTION-OPERATOR \
    --occurred-at 2026-07-30T12:03:00Z
docker run --rm \
  --volume "$workspace:/proof:ro" \
  "$PYTHON_IMAGE" \
  python -c 'import json,pathlib
records=[
  json.loads(line)
  for line in pathlib.Path("/proof/release-ledger.jsonl").read_text().splitlines()
]
assert [record["event"] for record in records]==[
  "staging_started","staging_verified",
  "production_started","production_verified",
]
assert len({record["manifestSha256"] for record in records})==1'
cp "$backup_manifest" "$manifest_proof_directory/manifest.json"
docker run --rm \
  --env "EXPECTED_PROJECT=$project" \
  --volume "$manifest_proof_directory:/proof:ro" \
  "$PYTHON_IMAGE" \
  python -c 'import json,os,pathlib
value=json.loads(pathlib.Path("/proof/manifest.json").read_text(encoding="utf-8"))
assert value["sourceProject"]==os.environ["EXPECTED_PROJECT"]
assert set(value["files"])=={
  "core.dump","twenty.dump","twenty-storage.tar","rustfs-data.tar"
}'

cp "$env_file" "$target_env_file"
printf '%s\n' "LEONAID_COMPOSE_PROJECT=$restore_project" >>"$target_env_file"
chmod 600 "$target_env_file"
set +e
wrong_restore_output=$(
  LEONAID_PILOT_TEST_COMPOSE_OVERLAY="$root/infra/pilot/compose.test.yml" \
    LEONAID_PILOT_TEST_RESTORE_OVERLAY="$root/infra/pilot/compose.test.yml" \
    LEONAID_PILOT_TEST_DECISIONS_FILE="$accepted_decisions" \
    LEONAID_PILOT_TEST_DOCTOR_NETWORK="container:$proxy_id" \
    LEONAID_PILOT_TEST_CA_FILE="$ca_file" \
    LEONAID_PILOT_TEST_HTTP_PORT="$restore_http_port" \
    LEONAID_PILOT_TEST_HTTPS_PORT="$restore_https_port" \
    LEONAID_TEST_CORE_IMAGE="$core_image" \
    LEONAID_TEST_WEB_IMAGE="$web_image" \
    LEONAID_TEST_PWA_IMAGE="$pwa_image" \
    LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
    "$root/leonaid" pilot-restore \
      --env-file "$env_file" \
      --backup-manifest "$backup_manifest" \
      --target-env-file "$target_env_file" \
      --password-file "$restic_password_file" \
      --credentials-file "$backup_credentials_file" \
      --confirm "RESTORE:wrong-target" 2>&1
)
wrong_restore_status=$?
set -e
if [ "$wrong_restore_status" -eq 0 ]; then
  echo "pilot-deployment-test: ERROR: falsche Restore-Bestätigung wurde akzeptiert" >&2
  exit 1
fi
if ! printf '%s' "$wrong_restore_output" |
  grep -Fq "muss exakt RESTORE:$restore_project sein"; then
  echo "pilot-deployment-test: ERROR: Restore-Ablehnung ist nicht diagnostizierbar" >&2
  exit 1
fi
LEONAID_PILOT_TEST_COMPOSE_OVERLAY="$root/infra/pilot/compose.test.yml" \
  LEONAID_PILOT_TEST_RESTORE_OVERLAY="$root/infra/pilot/compose.test.yml" \
  LEONAID_PILOT_TEST_DECISIONS_FILE="$accepted_decisions" \
  LEONAID_PILOT_TEST_DOCTOR_NETWORK="container:$proxy_id" \
  LEONAID_PILOT_TEST_CA_FILE="$ca_file" \
  LEONAID_PILOT_TEST_HTTP_PORT="$restore_http_port" \
  LEONAID_PILOT_TEST_HTTPS_PORT="$restore_https_port" \
  LEONAID_TEST_CORE_IMAGE="$core_image" \
  LEONAID_TEST_WEB_IMAGE="$web_image" \
  LEONAID_TEST_PWA_IMAGE="$pwa_image" \
  LEONAID_TEST_PUBLIC_IMAGE="$public_image" \
  "$root/leonaid" pilot-restore \
    --env-file "$env_file" \
    --backup-manifest "$backup_manifest" \
    --target-env-file "$target_env_file" \
    --password-file "$restic_password_file" \
    --credentials-file "$backup_credentials_file" \
    --confirm "RESTORE:$restore_project"
restore_compose exec -T core-postgres psql \
  --username "${CORE_POSTGRES_USER:-leonaid}" \
  --dbname "${CORE_POSTGRES_DB:-leonaid}" \
  --tuples-only --no-align \
  --command "SELECT value FROM pilot_operator_probe" |
  grep -Fx "core-operator-backup" >/dev/null
restore_compose exec -T twenty-postgres psql \
  --username "${TWENTY_POSTGRES_USER:-twenty}" \
  --dbname "${TWENTY_POSTGRES_DB:-default}" \
  --tuples-only --no-align \
  --command "SELECT value FROM public.pilot_operator_probe" |
  grep -Fx "twenty-operator-backup" >/dev/null
docker run --rm \
  --volume "${restore_project}_rustfs-data:/data:ro" \
  "$ALPINE_IMAGE" \
  grep -Fx "rustfs-operator-backup" /data/pilot-operator-probe >/dev/null
docker run --rm \
  --volume "${restore_project}_twenty-server-data:/data:ro" \
  "$ALPINE_IMAGE" \
  grep -Fx "twenty-storage-operator-backup" /data/pilot-operator-probe >/dev/null

echo "pilot-deployment-test: OK: Contract, Leerstart und realer Deployment Doctor bewiesen"
echo "pilot-deployment-test: OK: Operator-Deploy ist manifestgebunden, fail-closed und buildfrei"
echo "pilot-deployment-test: OK: Operator-Release erzwingt Staging, Backup, Wartung und Migrationen"
echo "pilot-deployment-test: OK: Operator-Backup/Restore erhält vier reale Datenkomponenten"
