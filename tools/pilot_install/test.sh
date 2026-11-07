#!/bin/sh
# End-to-end proof of ./leonaid pilot-install against real services in an
# isolated, owned Compose project: real Twenty with e-mail verification, real
# S3/Restic backup target, real TLS proxy, real Prometheus/Alertmanager, a real
# implicit-TLS+AUTH SMTP relay (Mailpit, port 465) that receives mail from
# Twenty and the core worker over the mail egress network, and the scheduled
# CRM match key repair including its maintenance-mode skip. Then
# the CMS: pilot-cms-provision with a failure halfway and its resumption, the
# System Admin's setup, a published campaign page on the public host, a
# repeat without changes, backups with the CMS data and a restore drill.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project="${LEONAID_PILOT_INSTALL_PROJECT:-leonaid-production-test-install}-$suffix"
build_project="leonaid-pilot-install-images-$suffix"
operator_backup_project="leonaid-pilot-install-backup-$suffix"
operator_backup_container="$operator_backup_project-rustfs"
operator_backup_volume="$operator_backup_project-rustfs-data"
operator_backup_bucket=leonaid-pilot-install
operator_mail_project="leonaid-pilot-install-mail-$suffix"
operator_mail_container="$operator_mail_project-mailpit"
set -- $(python3 - "${LEONAID_PILOT_TEST_HTTP_PORT:-0}" \
  "${LEONAID_PILOT_TEST_HTTPS_PORT:-0}" \
  "${LEONAID_PILOT_TEST_ADMIN_PORT:-0}" 0 <<'PORTS'
import socket, sys
sockets = []
for value in sys.argv[1:]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", int(value)))
    sockets.append(sock)
print(" ".join(str(sock.getsockname()[1]) for sock in sockets))
PORTS
)
[ "$#" -eq 4 ] || { echo 'pilot-install-test: port allocation failed' >&2; exit 1; }
export LEONAID_PILOT_TEST_HTTP_PORT="$1"
export LEONAID_PILOT_TEST_HTTPS_PORT="$2"
# Loopback port of the admin-only Twenty UI (TWENTY_ADMIN_PORT).
admin_port=$3
# Twenty admin port of the CMS restore drill's target project.
restore_admin_port=$4
workspace=$(mktemp -d)
mkdir -p "$workspace/evidence" "$workspace/session" "$root/.artifacts"
overlay_directory=$(mktemp -d "$root/.artifacts/pilot-install.XXXXXX")
overlay="$overlay_directory/overlay.yml"
env_file="$workspace/production.env"
bootstrap_file="$workspace/twenty-bootstrap.env"
restic_password_file="$workspace/restic-password"
backup_credentials_file="$workspace/backup-s3.env"
alert_webhook_file="$workspace/alert-webhook-url"
alert_heartbeat_file="$workspace/alert-heartbeat-url"
backup_manifest="$workspace/evidence/latest-backup-manifest.json"
release_manifest="$workspace/release-manifest.json"
accepted_decisions="$workspace/accepted-decisions.md"
install_log="$workspace/pilot-install.log"
release_commit=$(git -C "$root" rev-parse HEAD)
image_services="api web pwa public survey-validator proxy campaign-site"
runtime_owned=false
restore_owned=false
restore_project=
backup_owned=false
build_owned=false
mail_owned=false
mail_directory="$workspace/smtp"
mail_host=smtp.leonaid.org

export LEONAID_PILOT_TEST_COMPOSE_OVERLAY="$overlay"

runtime_compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/pilot/compose.yml" \
    --file "$overlay" \
    "$@"
}

leonaid_test() {
  LEONAID_PILOT_TEST_DECISIONS_FILE="$accepted_decisions" \
    LEONAID_PILOT_TEST_DOCTOR_NETWORK="container:$project-proxy-1" \
    LEONAID_PILOT_TEST_CA_FILE=proxy-data \
    "$root/leonaid" "$@"
}

verify_project_absent() {
  checked=$1
  [ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$checked")" ] &&
    [ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$checked")" ] &&
    [ -z "$(docker network ls -q --filter "label=com.docker.compose.project=$checked")" ]
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$runtime_owned" = true ]; then
    echo "pilot-install-test: diagnosis of the failed project:" >&2
    runtime_compose --profile monitoring ps --all >&2 || true
    runtime_compose --profile '*' logs --no-color --tail=60 \
      twenty-server api proxy alertmanager campaign-site >&2 || true
  fi
  if [ "$mail_owned" = true ]; then
    docker rm --force "$operator_mail_container" >/dev/null 2>&1 || status=1
  fi
  if [ "$restore_owned" = true ]; then
    restore_compose --profile '*' down --volumes --remove-orphans \
      >/dev/null 2>&1 || status=1
    verify_owned_project_removed "$restore_project" || status=1
  fi
  if [ "$runtime_owned" = true ]; then
    runtime_compose --profile '*' down --volumes --remove-orphans \
      >/dev/null 2>&1 || status=1
    verify_owned_project_removed "$project" || status=1
  fi
  if [ "$backup_owned" = true ]; then
    docker rm --force "$operator_backup_container" >/dev/null 2>&1 || status=1
    docker volume rm "$operator_backup_volume" >/dev/null 2>&1 || status=1
  fi
  if [ "$build_owned" = true ]; then
    for service in $image_services; do
      docker image rm "$build_project-$service:latest" >/dev/null 2>&1 || status=1
    done
    verify_owned_project_removed "$build_project" || status=1
  fi
  rm -rf "$overlay_directory" "$workspace"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

expect_refusal() {
  label=$1
  expected=$2
  shift 2
  set +e
  output=$(leonaid_test pilot-install "$@" 2>&1)
  refusal_status=$?
  set -e
  if [ "$refusal_status" -eq 0 ]; then
    echo "pilot-install-test: ERROR: $label was accepted" >&2
    exit 1
  fi
  if ! printf '%s' "$output" | grep -Fq "$expected"; then
    echo "pilot-install-test: ERROR: $label refused without '$expected':" >&2
    printf '%s\n' "$output" >&2
    exit 1
  fi
  echo "pilot-install-test: refused as expected: $label"
}

for owned in "$project" "$build_project" "$operator_backup_project" "$operator_mail_project"; do
  verify_project_absent "$owned"
done

echo "pilot-install-test: builds the seven release images"
build_owned=true
docker compose \
  --project-name "$build_project" \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
  --profile emdash \
  build $image_services
image_id() {
  docker image inspect --format '{{.Id}}' "$build_project-$1:latest"
}
LEONAID_TEST_CORE_IMAGE=$(image_id api)
LEONAID_TEST_WEB_IMAGE=$(image_id web)
LEONAID_TEST_PWA_IMAGE=$(image_id pwa)
LEONAID_TEST_PUBLIC_IMAGE=$(image_id public)
LEONAID_TEST_SURVEY_VALIDATOR_IMAGE=$(image_id survey-validator)
LEONAID_TEST_PROXY_IMAGE=$(image_id proxy)
LEONAID_TEST_CAMPAIGN_SITE_IMAGE=$(image_id campaign-site)
export LEONAID_TEST_CORE_IMAGE LEONAID_TEST_WEB_IMAGE LEONAID_TEST_PWA_IMAGE \
  LEONAID_TEST_PUBLIC_IMAGE LEONAID_TEST_SURVEY_VALIDATOR_IMAGE \
  LEONAID_TEST_PROXY_IMAGE LEONAID_TEST_CAMPAIGN_SITE_IMAGE

LEONAID_TEST_EXTRA_NETWORKS=mail-egress,crm-admin \
  python3 "$root/tools/surveys/network_override.py" "$overlay_directory/networks.yml"

echo "pilot-install-test: starts the operator's external S3 backup target"
backup_owned=true
backup_access_key=pilot-install-backup-access-001
backup_secret_key=pilot-install-backup-secret-002
docker volume create \
  --label "com.docker.compose.project=$operator_backup_project" \
  "$operator_backup_volume" >/dev/null
docker run --detach \
  --name "$operator_backup_container" \
  --label "com.docker.compose.project=$operator_backup_project" \
  --env "RUSTFS_ACCESS_KEY=$backup_access_key" \
  --env "RUSTFS_SECRET_KEY=$backup_secret_key" \
  --volume "$operator_backup_volume:/data" \
  --health-cmd 'curl --fail http://localhost:9000/health' \
  --health-interval 2s --health-timeout 2s --health-retries 30 \
  "$RUSTFS_IMAGE" /data >/dev/null
attempts=0
until [ "$(docker inspect --format '{{.State.Health.Status}}' "$operator_backup_container")" = healthy ]; do
  attempts=$((attempts + 1))
  [ "$attempts" -lt 60 ] || { echo 'pilot-install-test: backup target not ready' >&2; exit 1; }
  sleep 1
done
backup_ip=$(docker inspect \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
  "$operator_backup_container")
[ -n "$backup_ip" ]
docker run --rm \
  --volume "$root:/workspace:ro" --workdir /workspace \
  "$PYTHON_IMAGE" \
  /workspace/.venv/bin/python -c "import boto3
boto3.client('s3', endpoint_url='http://$backup_ip:9000',
  aws_access_key_id='$backup_access_key',
  aws_secret_access_key='$backup_secret_key',
  region_name='us-east-1').create_bucket(Bucket='$operator_backup_bucket')"

echo "pilot-install-test: writes production secrets with pilot-secrets"
"$root/leonaid" pilot-secrets --output "$env_file" >"$workspace/pilot-secrets.log"
grep -Fq 'fill in these keys by hand' "$workspace/pilot-secrets.log"
set +e
second_secrets=$("$root/leonaid" pilot-secrets --output "$env_file" 2>&1)
second_status=$?
set -e
[ "$second_status" -ne 0 ] && printf '%s' "$second_secrets" | grep -Fq 'refusing to overwrite' || {
  echo 'pilot-install-test: ERROR: pilot-secrets overwrote an existing file' >&2
  exit 1
}

# Fill the operator-supplied, non-generated values exactly as an operator
# would; every generated secret stays untouched.
printf '%s\n' "https://alerts.leonaid.org/pilot-install" >"$alert_webhook_file"
printf '%s\n' "https://heartbeat.leonaid.org/pilot-install" >"$alert_heartbeat_file"
chmod 600 "$alert_webhook_file" "$alert_heartbeat_file"
# As in the runbook: Alertmanager runs as nobody (65534) and reads both URL
# files, which stay private (0400) to that account.
# host-write-user: chown to the Alertmanager uid requires root
docker run --rm --volume "$workspace:/secrets" "$ALPINE_IMAGE" \
  sh -eu -c 'chown 65534:65534 /secrets/alert-webhook-url /secrets/alert-heartbeat-url
chmod 0400 /secrets/alert-webhook-url /secrets/alert-heartbeat-url'
digest=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env "PROJECT=$project" \
  --env "COMMIT=$release_commit" \
  --env "DIGEST=$digest" \
  --env "REPOSITORY=s3:http://$backup_ip:9000/$operator_backup_bucket" \
  --env "WORKSPACE=$workspace" \
  --env "ADMIN_PORT=$admin_port" \
  --volume "$workspace:$workspace" \
  "$PYTHON_IMAGE" \
  python -c 'import os, pathlib, secrets, string
w = os.environ["WORKSPACE"]
path = pathlib.Path(w) / "production.env"
values = {
  "LEONAID_COMPOSE_PROJECT": os.environ["PROJECT"],
  "LEONAID_SERVICE_VERSION": "2026.11.1",
  "LEONAID_RELEASE_COMMIT": os.environ["COMMIT"],
  "LEONAID_CLUB_NAME": "Lions Club Beispielstadt",
  "LEONAID_PUBLIC_DOMAIN": "portal.leonaid.org",
  "LEONAID_PUBLIC_BASE_URL": "https://portal.leonaid.org",
  "LEONAID_ALLOWED_ORIGINS": "https://portal.leonaid.org",
  "TWENTY_ADMIN_PORT": os.environ["ADMIN_PORT"],
  "CADDY_ACME_EMAIL": "operations@leonaid.org",
  "RUSTFS_BUCKET": "leonaid-production-club-111",
  "RESTIC_REPOSITORY": os.environ["REPOSITORY"],
  "LEONAID_BACKUP_MANIFEST_PATH": w + "/evidence/latest-backup-manifest.json",
  "LEONAID_MONITORED_DISK_PATH": w,
  "LEONAID_ALERT_WEBHOOK_URL_FILE": w + "/alert-webhook-url",
  "LEONAID_ALERT_HEARTBEAT_URL_FILE": w + "/alert-heartbeat-url",
  "MAIL_HEALTH_URL": "https://portal.leonaid.org/_health",
  "MAIL_SMTP_HOST": "smtp.leonaid.org",
  "TWENTY_MAIL_FROM_ADDRESS": "crm@leonaid.org",
  "MAIL_FROM": "LeonAid <noreply@leonaid.org>",
  "MAIL_ENVELOPE_FROM": "bounces@leonaid.org",
  "MAIL_REPLY_TO": "support@leonaid.org",
  "MAIL_SMTP_USERNAME": "pilot-install-smtp",
  "MAIL_SMTP_PASSWORD": "".join(
    secrets.choice(string.ascii_letters + string.digits) for _ in range(32)
  ),
}
for name in ("CORE", "WEB", "PWA", "PUBLIC", "PROXY", "SURVEY_VALIDATOR", "CAMPAIGN_SITE"):
  values[f"LEONAID_{name}_IMAGE"] = (
    f"registry.leonaid.org/leonaid/{name.lower()}@sha256:" + os.environ["DIGEST"]
  )
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
  key = line.split("=", 1)[0]
  lines.append(f"{key}={values.pop(key)}" if key in values and "=" in line else line)
assert not values, values
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
alphabet = string.ascii_letters + string.digits
(pathlib.Path(w) / "twenty-bootstrap.env").write_text(
  "TWENTY_BOOTSTRAP_EMAIL=install-admin@leonaid.org\n"
  "TWENTY_BOOTSTRAP_PASSWORD="
  + "".join(secrets.choice(alphabet) for _ in range(32)) + "\n",
  encoding="utf-8",
)
(pathlib.Path(w) / "restic-password").write_text(secrets.token_urlsafe(48) + "\n")
(pathlib.Path(w) / "backup-s3.env").write_text(
  "AWS_ACCESS_KEY_ID=pilot-install-backup-access-001\n"
  "AWS_SECRET_ACCESS_KEY=pilot-install-backup-secret-002\n"
  "AWS_DEFAULT_REGION=us-east-1\nAWS_REGION=us-east-1\n"
)'
chmod 600 "$env_file" "$bootstrap_file" "$restic_password_file" "$backup_credentials_file"
if grep -q '__[A-Z0-9_]*__' "$env_file"; then
  echo 'pilot-install-test: ERROR: placeholders remain in the env file' >&2
  exit 1
fi

# The template's MAIL_SMTP_MODE=tls on port 465 stays: only implicit TLS lets
# Twenty send mail.
grep -qx 'MAIL_SMTP_MODE=tls' "$env_file" && grep -qx 'MAIL_SMTP_PORT=465' "$env_file" || {
  echo 'pilot-install-test: ERROR: the template does not default to implicit TLS' >&2
  exit 1
}
echo "pilot-install-test: starts the operator's SMTP relay (implicit TLS, AUTH, test CA)"
mkdir -p "$mail_directory"
chmod 755 "$mail_directory"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$root:/repo:ro" \
  --volume "$mail_directory:/smtp" \
  --entrypoint python \
  "$LEONAID_TEST_CORE_IMAGE" \
  /repo/tools/pilot_install/mail_proof.py certificates /smtp "$mail_host"
smtp_user=$(sed -n 's/^MAIL_SMTP_USERNAME=//p' "$env_file")
smtp_password=$(sed -n 's/^MAIL_SMTP_PASSWORD=//p' "$env_file")
# Credentials reach Mailpit through a private env file, not the process list.
printf 'MP_SMTP_AUTH=%s:%s\n' "$smtp_user" "$smtp_password" >"$workspace/mailpit.env"
chmod 600 "$workspace/mailpit.env"
mail_owned=true
docker run --detach \
  --name "$operator_mail_container" \
  --label "com.docker.compose.project=$operator_mail_project" \
  --env-file "$workspace/mailpit.env" \
  --env MP_SMTP_BIND_ADDR=0.0.0.0:465 \
  --env MP_SMTP_TLS_CERT=/smtp/cert.pem \
  --env MP_SMTP_TLS_KEY=/smtp/key.pem \
  --env MP_SMTP_REQUIRE_TLS=true \
  --env MP_DATABASE=/tmp/mailpit.db \
  --volume "$mail_directory:/smtp:ro" \
  "$MAILPIT_IMAGE" >/dev/null
rm -f "$workspace/mailpit.env"

# The proxy runs the product's own single-host route table (the generated
# infra/pilot/Caddyfile, campaign routes included) with an internal CA instead
# of ACME.
python3 "$root/tools/proxy/caddyfiles.py" --render pilot-single --tls-internal \
  >"$overlay_directory/Caddyfile.pilot-single-test"
# Test-only additions: Twenty and the core worker trust the relay's test CA.
# Production relays need a certificate from a public CA.
write_overlay() {
python3 - "$root/infra/pilot/compose.test.yml" "$1" "$2" "$mail_directory/ca.pem" "$overlay_directory/Caddyfile.pilot-single-test" <<'OVERLAY'
from pathlib import Path
import sys
base, network, target, ca, caddyfile = sys.argv[1:]
text = Path(base).read_text()
mounted = "      - ../pilot/Caddyfile.test:/etc/caddy/Caddyfile:ro\n"
assert text.count(mounted) == 1
text = text.replace(mounted, f"      - {caddyfile}:/etc/caddy/Caddyfile:ro\n")
anchor = "  worker:\n    image: ${LEONAID_TEST_CORE_IMAGE:?LEONAID_TEST_CORE_IMAGE is missing}\n"
assert text.count(anchor) == 1
mount = (
    "    configs:\n"
    "      - source: smtp-test-ca\n"
    "        target: /run/leonaid-test/smtp-ca.pem\n"
)
# The core worker's default TLS context (no MAIL_SMTP_CA_FILE in the pilot)
# reads the trust store from SSL_CERT_FILE: test relay CA only, test only.
text = text.replace(
    anchor,
    anchor
    + "    environment:\n"
    + "      SSL_CERT_FILE: /run/leonaid-test/smtp-ca.pem\n"
    + mount
    + "\n  twenty-worker:\n"
    + "    environment:\n"
    + "      NODE_EXTRA_CA_CERTS: /run/leonaid-test/smtp-ca.pem\n"
    + mount,
)
text += (
    "\nconfigs:\n  smtp-test-ca:\n    file: " + ca + "\n"
    "\nnetworks:\n" + Path(network).read_text().split("\nnetworks:\n", 1)[1]
)
Path(target).write_text(text)
OVERLAY
}
write_overlay "$overlay_directory/networks.yml" "$overlay"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import pathlib
source = pathlib.Path("/workspace/specs/leonaid-pilot/DECISIONS.md")
lines = []
for line in source.read_text(encoding="utf-8").splitlines():
    if line.startswith("| PILOT-"):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        decision = cells[0]
        cells[6] = "EVID-TEST-" + decision.removeprefix("PILOT-")
        cells[7] = "accepted"
        cells[8] = (
            "small_business" if decision == "PILOT-TAX-001"
            else "not_required" if decision == "PILOT-INV-002"
            else "confirmed"
        )
        line = "| " + " | ".join(cells) + " |"
    lines.append(line)
target = pathlib.Path("/proof/accepted-decisions.md")
target.write_text("\n".join(lines) + "\n", encoding="utf-8")
target.chmod(0o600)'

echo "pilot-install-test: creates the release manifest for this checkout"
runtime_compose config --format json >"$workspace/runtime-compose.json"
docker run --rm --interactive \
  --user "$(id -u):$(id -g)" \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  sh -eu -c 'cat > /tmp/runtime-compose.json; exec python tools/pilot_release/manifest.py create "$@"' sh \
    --root /workspace \
    --release-id pilot-install-test \
    --version 2026.11.1 \
    --git-commit "$release_commit" \
    --deployment-mode test \
    --compose-config /tmp/runtime-compose.json \
    --output /proof/release-manifest.json <"$workspace/runtime-compose.json"

echo "pilot-install-test: proves the guards before any container starts"
chmod 644 "$env_file"
expect_refusal "world-readable env file" "environment file must have mode 0600" \
  --env-file "$env_file" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$bootstrap_file" --password-file "$restic_password_file"
chmod 600 "$env_file"
cp "$bootstrap_file" "$overlay_directory/twenty-bootstrap.env"
chmod 600 "$overlay_directory/twenty-bootstrap.env"
expect_refusal "bootstrap file inside the checkout" "must live outside the checkout" \
  --env-file "$env_file" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$overlay_directory/twenty-bootstrap.env" \
  --password-file "$restic_password_file"
rm -f "$overlay_directory/twenty-bootstrap.env"
sed 's/^TWENTY_BOOTSTRAP_PASSWORD=.*/TWENTY_BOOTSTRAP_PASSWORD=short/' \
  "$bootstrap_file" >"$workspace/weak-bootstrap.env"
chmod 600 "$workspace/weak-bootstrap.env"
expect_refusal "weak bootstrap password" "at least 16 letters or digits" \
  --env-file "$env_file" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$workspace/weak-bootstrap.env" \
  --password-file "$restic_password_file"
sed 's/^TWENTY_INTEGRATION_API_KEY=.*/TWENTY_INTEGRATION_API_KEY=already-provisioned-key-0123456789abcdef/' \
  "$env_file" >"$workspace/provisioned.env"
chmod 600 "$workspace/provisioned.env"
expect_refusal "provisioned integration key" "is not PENDING_PILOT_INSTALL" \
  --env-file "$workspace/provisioned.env" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$bootstrap_file" --password-file "$restic_password_file"
sed 's/^LEONAID_CMS_ENABLED=false$/LEONAID_CMS_ENABLED=true/' \
  "$env_file" >"$workspace/cms-install.env"
chmod 600 "$workspace/cms-install.env"
grep -qx 'LEONAID_CMS_ENABLED=true' "$workspace/cms-install.env"
expect_refusal "CMS enabled at the first install" "install with LEONAID_CMS_ENABLED=false" \
  --env-file "$workspace/cms-install.env" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$bootstrap_file" --password-file "$restic_password_file"
verify_project_absent "$project" || {
  echo 'pilot-install-test: ERROR: a refused install left resources behind' >&2
  exit 1
}

echo "pilot-install-test: runs pilot-install on the empty project"
runtime_owned=true
# The subnets were only free when the overlay was written; reserve them now so
# a concurrent stack cannot take them before Compose creates the networks.
runtime_compose --profile '*' config --format json |
  python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$overlay"
leonaid_test pilot-install \
  --env-file "$env_file" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$bootstrap_file" --password-file "$restic_password_file" \
  --credentials-file "$backup_credentials_file" 2>&1 | tee "$install_log"
# tee hides the exit status of pilot-install; its last line proves success.
grep -Fq "pilot-install: OK: $project runs release $release_commit" "$install_log" || {
  echo 'pilot-install-test: ERROR: pilot-install did not finish' >&2
  exit 1
}

echo "pilot-install-test: checks the installed state"
key=$(sed -n 's/^TWENTY_INTEGRATION_API_KEY=//p' "$env_file")
[ "$(grep -c '^TWENTY_INTEGRATION_API_KEY=' "$env_file")" -eq 1 ]
[ "$key" != PENDING_PILOT_INSTALL ] && [ "${#key}" -ge 32 ] || {
  echo 'pilot-install-test: ERROR: the integration key was not written' >&2
  exit 1
}
case "$(ls -l "$env_file")" in
  -rw-------*) ;;
  *) echo 'pilot-install-test: ERROR: the env file lost mode 0600' >&2; exit 1 ;;
esac
bootstrap_password=$(sed -n 's/^TWENTY_BOOTSTRAP_PASSWORD=//p' "$bootstrap_file")
if grep -Fq "$key" "$install_log" || grep -Fq "$bootstrap_password" "$install_log"; then
  echo 'pilot-install-test: ERROR: pilot-install printed a secret' >&2
  exit 1
fi

expected_services=$(printf '%s\n' \
  alertmanager api core-postgres pilot-exporter prometheus proxy public pwa \
  rustfs survey-validator twenty-postgres twenty-redis twenty-server \
  twenty-worker web worker | sort)
actual_services=$(runtime_compose --profile monitoring ps --services --filter status=running | sort)
[ "$actual_services" = "$expected_services" ] || {
  echo "pilot-install-test: ERROR: running services differ:" >&2
  printf '%s\n' "$actual_services" >&2
  exit 1
}
for service in twenty-server twenty-worker; do
  verification=$(runtime_compose exec -T "$service" printenv IS_EMAIL_VERIFICATION_REQUIRED)
  [ "$verification" = true ] || {
    echo "pilot-install-test: ERROR: $service runs without e-mail verification" >&2
    exit 1
  }
  # The mail policy in the entrypoint exports the driver; node inherits it.
  driver=$(runtime_compose exec -T "$service" sh -c \
    'for p in /proc/[0-9]*; do tr "\\0" "\\n" <"$p/environ" 2>/dev/null; done | sed -n "s/^EMAIL_DRIVER=//p" | sort -u')
  [ "$driver" = SMTP ] || {
    echo "pilot-install-test: ERROR: $service runs EMAIL_DRIVER '$driver' with implicit TLS" >&2
    exit 1
  }
done
# Admin-only CRM: Twenty answers on the loopback port, not through the proxy.
curl --fail --silent "http://127.0.0.1:$admin_port/healthz" | grep -q '"status":"ok"'

verification_probe() {
  runtime_compose run --rm --no-deps \
    --user "$(id -u):$(id -g)" --env HOME=/tmp \
    --env-from-file "$bootstrap_file" \
    --env PYTHONPATH=/repo:/workspace/src \
    --volume "$root:/repo:ro" --workdir /repo --entrypoint python \
    api tools/pilot_install/verification_probe.py "$1"
}
set_admin_verified() {
  printf '%s\n' "UPDATE core.\"user\" SET \"isEmailVerified\" = $1 WHERE \"email\" = 'install-admin@leonaid.org';" |
    runtime_compose exec -T twenty-postgres \
      psql --quiet --set ON_ERROR_STOP=1 --username twenty --dbname default
}
verification_probe verified
# Why pilot-install verifies the address: the same admin without the flag is
# refused by the production setting.
set_admin_verified false
verification_probe refused
set_admin_verified true
verification_probe verified

cp "$backup_manifest" "$workspace/manifest-copy.json"
docker run --rm \
  --env "EXPECTED_PROJECT=$project" \
  --volume "$workspace/manifest-copy.json:/proof/manifest.json:ro" \
  "$PYTHON_IMAGE" \
  python -c 'import json, os, pathlib
value = json.loads(pathlib.Path("/proof/manifest.json").read_text(encoding="utf-8"))
assert value["sourceProject"] == os.environ["EXPECTED_PROJECT"]
# The pilot proxy keeps its certificates in caddy-data, so the backup has it.
assert set(value["files"]) == {"core.dump", "twenty.dump", "twenty-storage.tar", "rustfs-data.tar", "caddy-data.tar"}, sorted(value["files"])'

echo "pilot-install-test: proves mail from Twenty and the core worker through the relay"
# The relay joins the egress network under its public name, like an external
# provider that only the mail egress can reach.
docker network connect --alias "$mail_host" "${project}_mail-egress" \
  "$operator_mail_container"
mail_api="http://$mail_host:8025"
assert_delivered() {
  docker run --rm --network "${project}_mail-egress" \
    --volume "$root:/workspace:ro" --workdir /workspace \
    "$PYTHON_IMAGE" \
    python tools/pilot_install/mail_proof.py assert-delivered "$mail_api" "$@"
}
runtime_compose exec -T api python - twenty-reset install-admin@leonaid.org \
  <"$root/tools/pilot_install/mail_proof.py"
assert_delivered install-admin@leonaid.org crm@leonaid.org assword
runtime_compose exec -T \
  --env MAIL_SMTP_CA_FILE=/run/leonaid-test/smtp-ca.pem \
  worker python - core-send relay-probe@leonaid.org \
  <"$root/tools/pilot_install/mail_proof.py"
assert_delivered relay-probe@leonaid.org noreply@leonaid.org "relay probe"

echo "pilot-install-test: proves the scheduled CRM match key repair"
expect_repair_refusal() {
  label=$1
  expected=$2
  shift 2
  set +e
  output=$(leonaid_test pilot-repair-crm-match-keys "$@" 2>&1)
  refusal_status=$?
  set -e
  if [ "$refusal_status" -eq 0 ] || ! printf '%s' "$output" | grep -Fq -- "$expected"; then
    echo "pilot-install-test: ERROR: repair $label was not refused with '$expected':" >&2
    printf '%s\n' "$output" >&2
    exit 1
  fi
  echo "pilot-install-test: refused as expected: repair $label"
}
expect_repair_refusal "without env file" "--env-file is missing"
expect_repair_refusal "with a zero window" "positive number of minutes" \
  --env-file "$env_file" --changed-within 0
chmod 644 "$env_file"
expect_repair_refusal "with a world-readable env file" "must have mode 0600" \
  --env-file "$env_file"
chmod 600 "$env_file"
crm_check() {
  runtime_compose exec -T api python -m leonaid.entrypoints.crm_match_keys --check
}
# A company created directly in Twenty, as an operator would in the CRM UI,
# carries no match key until the repair runs.
runtime_compose exec -T api python -c 'import json, os, urllib.request
request = urllib.request.Request(
    os.environ["TWENTY_BASE_URL"] + "/rest/companies",
    data=json.dumps({"name": "Repair Proof Pharmacy"}).encode(),
    headers={
        "Authorization": "Bearer " + os.environ["TWENTY_INTEGRATION_API_KEY"],
        "Content-Type": "application/json",
    },
    method="POST",
)
urllib.request.urlopen(request, timeout=30).read()'
crm_check | grep -q '"unkeyed":[1-9]' || {
  echo 'pilot-install-test: ERROR: the directly created company already has a key' >&2
  exit 1
}
leonaid_test pilot-repair-crm-match-keys --env-file "$env_file" --changed-within 30 \
  | tee "$workspace/repair.log"
grep -Fq 'crm-match-keys: OK:' "$workspace/repair.log"
if crm_check | grep -q '"unkeyed":[1-9]'; then
  echo 'pilot-install-test: ERROR: the repair left records without a key' >&2
  exit 1
fi
leonaid_test pilot-repair-crm-match-keys --env-file "$env_file" \
  | grep -Fq 'crm-match-keys: OK:'
# Maintenance mode stops Twenty on purpose: the timer run must skip with
# success instead of failing, and run again once maintenance ends.
maintenance() {
  LEONAID_ENV_FILE="$env_file" \
    LEONAID_COMPOSE_PROJECT="$project" \
    LEONAID_MAINTENANCE_COMPOSE_OVERLAY="$root/infra/pilot/compose.yml" \
    LEONAID_MAINTENANCE_COMPOSE_OVERLAY_SECONDARY="$overlay" \
    LEONAID_MAINTENANCE_NO_BUILD=true \
    /bin/sh "$root/infra/upgrade/maintenance.sh" "$1" "$root"
}
maintenance enable
leonaid_test pilot-repair-crm-match-keys --env-file "$env_file" --changed-within 30 \
  >"$workspace/repair-maintenance.log"
grep -Fq 'SKIPPED: '"$project"' is in maintenance mode' "$workspace/repair-maintenance.log" || {
  echo 'pilot-install-test: ERROR: the repair did not skip during maintenance' >&2
  cat "$workspace/repair-maintenance.log" >&2
  exit 1
}
maintenance disable
leonaid_test pilot-repair-crm-match-keys --env-file "$env_file" --changed-within 30 \
  | grep -Fq 'crm-match-keys: OK:'

echo "pilot-install-test: waits for the always-firing Watchdog in Alertmanager"
attempts=0
until docker run --rm --network "${project}_telemetry" \
  --volume "$root:/workspace:ro" --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/pilot_alerting/contract.py assert-alertmanager \
    --url http://alertmanager:9093/api/v2/alerts --alert LeonAidWatchdog \
    >/dev/null 2>&1; do
  attempts=$((attempts + 1))
  [ "$attempts" -lt 30 ] || {
    echo 'pilot-install-test: ERROR: Watchdog never reached Alertmanager' >&2
    exit 1
  }
  sleep 2
done

for secret in alert-webhook-url alert-heartbeat-url; do
  runtime_compose --profile monitoring exec -T alertmanager \
    cat "/run/secrets/$secret" >/dev/null || {
    echo "pilot-install-test: ERROR: Alertmanager cannot read $secret" >&2
    exit 1
  }
done

echo "pilot-install-test: proves the first System Admin (pilot-create-system-admin)"
create_admin() {
  set +e
  admin_output=$(leonaid_test pilot-create-system-admin --env-file "$env_file" "$@" 2>&1)
  admin_status=$?
  set -e
}
expect_admin() {
  label=$1
  expected_status=$2
  expected_text=$3
  shift 3
  create_admin "$@"
  if [ "$admin_status" -ne "$expected_status" ] ||
    ! printf '%s' "$admin_output" | grep -Fq -- "$expected_text"; then
    echo "pilot-install-test: ERROR: system admin $label: status $admin_status, expected $expected_status with '$expected_text':" >&2
    printf '%s\n' "$admin_output" | tail -n 15 >&2
    exit 1
  fi
  echo "pilot-install-test: system admin $label"
}
expect_admin "needs an address" 64 "--email is missing" --display-name "CMS System Admin"
expect_admin "creates the first one on an empty installation" 0 \
  "System Admin created; the sign-in mail for cms-admin@leonaid.org is queued" \
  --email Cms-Admin@leonaid.org --display-name "CMS System Admin"
# The normal sign-in mail through the relay: code and link, no password.
assert_delivered cms-admin@leonaid.org noreply@leonaid.org "LeonAid-Login"
expect_admin "repeats without a change" 0 "already is an active System Admin; nothing changed" \
  --email cms-admin@leonaid.org --display-name "CMS System Admin"
expect_admin "refuses a second one without --additional" 1 \
  "an active System Admin exists already; pass --additional" \
  --email cms-second-admin@leonaid.org --display-name "Second System Admin"
expect_admin "adds a second one with --additional" 0 "System Admin created" \
  --email cms-second-admin@leonaid.org --display-name "Second System Admin" --additional
assert_delivered cms-second-admin@leonaid.org noreply@leonaid.org "LeonAid-Login"
admin_audit=$(runtime_compose exec -T core-postgres psql --quiet --username leonaid --dbname leonaid \
  --tuples-only --no-align --command \
  "SELECT event_type || ':' || (actor_user_id IS NULL)::text FROM audit_event WHERE request_id LIKE 'pilot-create-system-admin:%' ORDER BY occurred_at")
[ "$admin_audit" = "$(printf '%s\n' identity.account.created:true identity.global_role.granted:true identity.login_challenge.created:true identity.account.created:true identity.global_role.granted:true identity.login_challenge.created:true)" ] || {
  echo "pilot-install-test: ERROR: unexpected system admin audit trail:" >&2
  printf '%s\n' "$admin_audit" >&2
  exit 1
}
if printf '%s' "$admin_output" | grep -Eq '[0-9]{6}'; then
  echo "pilot-install-test: ERROR: pilot-create-system-admin printed a code" >&2
  exit 1
fi

echo "pilot-install-test: proves CMS provisioning (pilot-cms-provision) end to end"
cms_release_manifest="$workspace/release-manifest-cms.json"
cms_admin_id=$(runtime_compose exec -T core-postgres psql --quiet --username leonaid \
  --dbname leonaid --tuples-only --no-align \
  --command "SELECT id FROM user_account WHERE email = 'cms-admin@leonaid.org'")
cms_admin_email=cms-admin@leonaid.org
cms_action_id=20000000-0000-4000-8000-0000000000c1
cms_slug=pilot-cms-proof
cms_title="Pilot CMS proof campaign"
core_sql() {
  runtime_compose exec -T core-postgres psql --quiet --set ON_ERROR_STOP=1 \
    --username leonaid --dbname leonaid "$@"
}
cms_provision() {
  leonaid_test pilot-cms-provision --env-file "$env_file" \
    --backup-manifest "$backup_manifest" \
    --release-manifest "$cms_manifest_argument" "$@"
}
# The CMS release manifest exists only once the CMS is enabled below.
cms_manifest_argument=$release_manifest
# Runs cms_provision and keeps its output and exit status for assertions.
cms_provision_capture() {
  set +e
  cms_output=$(cms_provision "$@" 2>&1)
  cms_status=$?
  set -e
  printf '%s\n' "$cms_output" >>"$workspace/cms-provision.log"
}
cms_expect() {
  label=$1
  expected_status=$2
  expected_text=$3
  shift 3
  cms_provision_capture "$@"
  if [ "$cms_status" -ne "$expected_status" ] ||
    ! printf '%s' "$cms_output" | grep -Fq -- "$expected_text"; then
    echo "pilot-install-test: ERROR: CMS $label: status $cms_status, expected $expected_status with '$expected_text':" >&2
    printf '%s\n' "$cms_output" | tail -n 25 >&2
    exit 1
  fi
  echo "pilot-install-test: CMS $label"
}
cms_state() {
  runtime_compose --profile emdash run --rm --no-deps --entrypoint node \
    campaign-site /app/operator/cms-provision-operator.mjs status
}
assert_backup_schema() {
  cp "$backup_manifest" "$workspace/manifest-copy.json"
  docker run --rm \
    --env "EXPECTED_SCHEMA=$1" \
    --volume "$workspace/manifest-copy.json:/proof/manifest.json:ro" \
    "$PYTHON_IMAGE" \
    python -c 'import json, os, pathlib
value = json.loads(pathlib.Path("/proof/manifest.json").read_text(encoding="utf-8"))
assert value["schemaVersion"] == int(os.environ["EXPECTED_SCHEMA"]), value["schemaVersion"]'
}
cms_proof() {
  cms_proof_run "$@" || {
    # Diagnosis without secrets: provisioning state and the Core identity
    # answer as the CMS sees it (status code and field names only).
    echo "pilot-install-test: CMS diagnosis after a failed edge proof:" >&2
    cms_state >&2 || true
    CMS_PROOF_SESSION=$cms_session runtime_compose --profile emdash exec -T \
      --env CMS_PROOF_SESSION campaign-site node -e '
fetch("http://api:8000/api/v1/identity/me", {
  headers: { Cookie: "__Host-leonaid_session=" + process.env.CMS_PROOF_SESSION },
  redirect: "manual",
}).then(async (r) => {
  const body = await r.text();
  let keys = [];
  try { keys = Object.keys(JSON.parse(body)); } catch {}
  console.error("core identity:", r.status, r.headers.get("content-type"), keys.join(","));
}).catch((e) => console.error("core identity: fetch failed", e?.cause?.code ?? e?.name));
const fs = require("node:fs");
try { const s = JSON.parse(fs.readFileSync("/app/bootstrap-state/state.json", "utf8"));
  console.error("bootstrap:", s.status, s.actor, s.expiresAt > Date.now() ? "valid" : "expired");
} catch (e) { console.error("bootstrap: unreadable", e?.code); }' >&2 || true
    exit 1
  }
}
cms_proof_run() {
  CMS_PROOF_SESSION=$cms_session docker run --rm \
    --network "container:$project-proxy-1" \
    --env CMS_PROOF_SESSION \
    --env CMS_PROOF_HOST=portal.leonaid.org \
    --env CMS_PROOF_CA_FILE=/caddy/caddy/pki/authorities/local/root.crt \
    --volume "${project}_caddy-data:/caddy:ro" \
    --volume "$root:/workspace:ro" --workdir /workspace \
    "$PYTHON_IMAGE" python tools/pilot_install/cms_proof.py "$@"
}
s3_root() {
  runtime_compose exec -T api python -c 'import boto3, json, os, sys
from botocore.config import Config
s3 = boto3.client("s3", endpoint_url="http://rustfs:9000",
  aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
  aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"], region_name="us-east-1",
  config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
if sys.argv[1] == "block":
    s3.create_bucket(Bucket="emdash-media")
    s3.put_bucket_policy(Bucket="emdash-media", Policy=json.dumps({
      "Version": "2012-10-17",
      "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]},
        "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::emdash-media/*"]}]}))
else:
    s3.delete_bucket_policy(Bucket="emdash-media")' "$1"
}

cms_expect "refused while LEONAID_CMS_ENABLED=false" 1 \
  "set LEONAID_CMS_ENABLED=true in the environment file first"

# Enable the CMS: the release now needs the CMS contract (manifest schema 2).
sed -i 's/^LEONAID_CMS_ENABLED=false$/LEONAID_CMS_ENABLED=true/' "$env_file"
grep -qx 'LEONAID_CMS_ENABLED=true' "$env_file"
cms_manifest_argument=$cms_release_manifest
runtime_compose --profile emdash config --format json >"$workspace/runtime-compose-cms.json"
docker run --rm --interactive \
  --user "$(id -u):$(id -g)" \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  sh -eu -c 'cat > /tmp/runtime-compose.json; exec python tools/pilot_release/manifest.py create "$@"' sh \
    --root /workspace \
    --release-id pilot-install-cms-test \
    --version 2026.11.1 \
    --git-commit "$release_commit" \
    --deployment-mode test \
    --schema-version 2 \
    --compose-config /tmp/runtime-compose.json \
    --output /proof/release-manifest-cms.json <"$workspace/runtime-compose-cms.json"

# LEONAID_CMS_ENABLED=true is not accepted before the CMS is provisioned.
set +e
deploy_output=$(leonaid_test pilot-deploy --env-file "$env_file" \
  --backup-manifest "$backup_manifest" \
  --release-manifest "$cms_release_manifest" 2>&1)
deploy_status=$?
set -e
[ "$deploy_status" -ne 0 ] &&
  printf '%s' "$deploy_output" | grep -Fq "the CMS is not provisioned" || {
  echo "pilot-install-test: ERROR: pilot-deploy accepted an unprovisioned CMS:" >&2
  printf '%s\n' "$deploy_output" | tail -n 20 >&2
  exit 1
}
[ -z "$(runtime_compose --profile emdash ps --quiet campaign-site)" ]
echo "pilot-install-test: CMS pilot-deploy refused before provisioning"

# Failure halfway: a foreign policy on the media bucket stops step 2 after
# step 1 succeeded; the next run resumes at step 2.
s3_root block
cms_expect "stops at a reviewed bucket policy" 1 "emdash-rustfs: FAILED"
printf '%s' "$cms_output" | grep -Fq "1/4 database: provisioning"
cms_state >"$workspace/cms-state.txt"
grep -qx 'database=ready' "$workspace/cms-state.txt"
grep -qx 'storage=missing' "$workspace/cms-state.txt"
grep -qx 'bootstrap=none' "$workspace/cms-state.txt"
s3_root unblock
cms_expect "resumes and needs the System Admin" 64 \
  "--system-admin-email of the LeonAid System Admin"
printf '%s' "$cms_output" | grep -Fq "1/4 database: already provisioned"
printf '%s' "$cms_output" | grep -Fq "2/4 media bucket: provisioning"

printf '%s\n' \
  "INSERT INTO user_account (id, email, display_name, status) VALUES ('10000000-0000-4000-8000-0000000000c2', 'cms-member@leonaid.org', 'CMS Member', 'active');" |
  core_sql
cms_expect "refuses a member without the System Admin role" 1 \
  "is no active LeonAid System Admin" --system-admin-email cms-member@leonaid.org
cms_expect "arms the setup grant" 75 "3/4 editor setup: PENDING" \
  --system-admin-email "$cms_admin_email"
printf '%s' "$cms_output" | grep -Fq "2/4 media bucket: already provisioned"
cms_state | grep -qx 'bootstrap=armed'
# Still pending: a repeat neither re-arms nor needs the address again.
cms_expect "waits for the setup" 75 "3/4 editor setup: PENDING"
# One grant at a time: another System Admin's address is refused, not ignored.
cms_expect "refuses a second System Admin while armed" 1 \
  "the setup is armed for another System Admin until" \
  --system-admin-email cms-second-admin@leonaid.org

# While provisioning is under way the nightly backup keeps working without
# the unfinished CMS; switching the CMS off again needs no restore.
leonaid_test pilot-backup --env-file "$env_file" --backup-manifest "$backup_manifest" \
  --password-file "$restic_password_file" --credentials-file "$backup_credentials_file" \
  >"$workspace/cms-pending-backup.log" 2>&1 || {
  echo "pilot-install-test: ERROR: pilot-backup failed while the CMS setup was pending" >&2
  tail -n 20 "$workspace/cms-pending-backup.log" >&2
  exit 1
}
grep -Fq "this backup does not contain the unfinished CMS" "$workspace/cms-pending-backup.log"
assert_backup_schema 1
sed -i 's/^LEONAID_CMS_ENABLED=true$/LEONAID_CMS_ENABLED=false/' "$env_file"
leonaid_test pilot-backup --env-file "$env_file" --backup-manifest "$backup_manifest" \
  --password-file "$restic_password_file" --credentials-file "$backup_credentials_file" \
  >"$workspace/cms-off-backup.log" 2>&1 || {
  echo "pilot-install-test: ERROR: pilot-backup failed after switching the CMS off again" >&2
  tail -n 20 "$workspace/cms-off-backup.log" >&2
  exit 1
}
grep -Fq "the unfinished CMS (setup not complete) is not part of this backup" \
  "$workspace/cms-off-backup.log"
leonaid_test pilot-doctor --env-file "$env_file" --backup-manifest "$backup_manifest" \
  --gate pilot-deploy >/dev/null
sed -i 's/^LEONAID_CMS_ENABLED=false$/LEONAID_CMS_ENABLED=true/' "$env_file"
echo "pilot-install-test: CMS backups and the switch-off work while the setup is pending"

# A refused setup request hands the grant back instead of locking the CMS.
# The System Admin signs in for real: the code of its sign-in mail.
login_code=$(docker run --rm --network "${project}_mail-egress" \
  --volume "$root:/workspace:ro" --workdir /workspace "$PYTHON_IMAGE" \
  python tools/pilot_install/mail_proof.py login-code "$mail_api" cms-admin@leonaid.org)
docker run --rm --network "container:$project-proxy-1" \
  --env CMS_PROOF_HOST=portal.leonaid.org \
  --env CMS_PROOF_CA_FILE=/caddy/caddy/pki/authorities/local/root.crt \
  --env CMS_PROOF_SESSION_FILE=/session/token \
  --volume "${project}_caddy-data:/caddy:ro" \
  --volume "$workspace/session:/session" \
  --user "$(id -u):$(id -g)" \
  --volume "$root:/workspace:ro" --workdir /workspace \
  "$PYTHON_IMAGE" python tools/pilot_install/cms_proof.py login cms-admin@leonaid.org "$login_code"
cms_session=$(cat "$workspace/session/token")
cms_proof setup-refused
cms_state | grep -qx 'bootstrap=armed'
# A grant left consumed (a crash during the setup request) is withdrawn only
# with --reset-setup, and only while the CMS is unused; Core audits it.
runtime_compose --profile emdash exec -T campaign-site node -e '
const fs = require("node:fs");
const path = "/app/bootstrap-state/state.json";
const state = JSON.parse(fs.readFileSync(path, "utf8"));
fs.writeFileSync(path, JSON.stringify({ ...state, status: "consumed" }));'
cms_expect "blocks at a consumed grant" 1 "run again with --reset-setup"
cms_expect "withdraws the unfinished grant and arms again" 75 \
  "3/4 editor setup: PENDING" --reset-setup --system-admin-email "$cms_admin_email"
printf '%s' "$cms_output" | grep -Fq "unfinished setup grant withdrawn"
audits=$(core_sql --tuples-only --no-align --command \
  "SELECT string_agg(event_type, ',' ORDER BY occurred_at) FROM audit_event WHERE entity_type = 'cms_setup_grant' AND entity_id = '$cms_admin_id'")
[ "$audits" = "cms.setup_grant.armed,cms.setup_grant.withdrawn,cms.setup_grant.armed" ] || {
  echo "pilot-install-test: ERROR: unexpected CMS setup audit trail: $audits" >&2
  exit 1
}
cms_proof setup
cms_expect "installs the campaign schema" 0 \
  "pilot-cms-provision: OK: $project serves the CMS"
printf '%s' "$cms_output" | grep -Fq "3/4 editor setup: already complete"
printf '%s' "$cms_output" | grep -Fq "4/4 campaign schema: installing"

# Step 4 interrupted between its installers (here after the binding guards):
# traffic closed, CMS stopped, media guards absent. The next run finishes it.
runtime_compose --profile emdash stop campaign-site >/dev/null
runtime_compose --profile emdash run --rm --no-deps --entrypoint mkdir \
  campaign-site /app/bootstrap-state/cms-maintenance
printf '%s\n' \
  "DROP TABLE public.leonaid_campaign_media;" \
  "DROP FUNCTION public.leonaid_campaign_media_guard();" \
  "DELETE FROM public.options WHERE name = 'leonaid:campaign_media_version';" |
  runtime_compose exec -T core-postgres psql --quiet --set ON_ERROR_STOP=1 \
    --username leonaid --dbname emdash
cms_state >"$workspace/cms-state.txt"
grep -qx 'schema=partial' "$workspace/cms-state.txt"
grep -qx 'traffic=closed' "$workspace/cms-state.txt"
cms_expect "resumes an interrupted schema install" 0 \
  "pilot-cms-provision: OK: $project serves the CMS"
printf '%s' "$cms_output" | grep -Fq "4/4 campaign schema: installing"
cms_expect "repeats as a no-op" 0 "pilot-cms-provision: OK: $project serves the CMS"
for step in "1/4 database: already" "2/4 media bucket: already" \
  "3/4 editor setup: already" "4/4 campaign schema: already"; do
  printf '%s' "$cms_output" | grep -Fq "$step"
done
if printf '%s' "$cms_output" | grep -Eq ': (provisioning|installing)'; then
  echo "pilot-install-test: ERROR: the repeated provisioning changed something" >&2
  exit 1
fi
# The grant is used up: the setup stays closed for good.
cms_proof setup-closed
for secret in CORE_POSTGRES_PASSWORD CMS_POSTGRES_PASSWORD CMS_S3_SECRET_ACCESS_KEY; do
  value=$(sed -n "s/^$secret=//p" "$env_file")
  if grep -Fq "$value" "$workspace/cms-provision.log"; then
    echo "pilot-install-test: ERROR: pilot-cms-provision printed $secret" >&2
    exit 1
  fi
done

# Backups take the CMS from now on; the doctor requires them.
leonaid_test pilot-backup --env-file "$env_file" --backup-manifest "$backup_manifest" \
  --password-file "$restic_password_file" --credentials-file "$backup_credentials_file"
assert_cms_backup() {
  cp "$backup_manifest" "$workspace/manifest-copy.json"
  docker run --rm \
    --env "EXPECTED_PROJECT=$project" \
    --volume "$workspace/manifest-copy.json:/proof/manifest.json:ro" \
    "$PYTHON_IMAGE" \
    python -c 'import json, os, pathlib
value = json.loads(pathlib.Path("/proof/manifest.json").read_text(encoding="utf-8"))
assert value["sourceProject"] == os.environ["EXPECTED_PROJECT"]
assert value["schemaVersion"] == 2, value["schemaVersion"]
assert set(value["files"]) == {"core.dump", "twenty.dump", "twenty-storage.tar", "rustfs-data.tar", "caddy-data.tar", "emdash.dump", "cms-bootstrap-state.tar"}, sorted(value["files"])'
}
assert_cms_backup
leonaid_test pilot-deploy --env-file "$env_file" \
  --backup-manifest "$backup_manifest" \
  --release-manifest "$cms_release_manifest" | tee "$workspace/cms-deploy.log"
grep -Fq "pilot-deploy: OK: $project runs exactly from the verified release manifest" \
  "$workspace/cms-deploy.log"
[ "$(docker inspect --format '{{.State.Health.Status}}' \
  "$(runtime_compose --profile emdash ps --quiet campaign-site)")" = healthy ]

# Publish a campaign page in the editor; the public host serves it. A Core
# campaign needs a responsible charity admin (action management invariant).
printf '%s\n' \
  "INSERT INTO charity_action (id, carrier_name, name, purpose, status, starts_on, ends_on, publication_starts_at, publication_ends_at, archive_slug) VALUES ('$cms_action_id', 'Lions Club Beispielstadt', 'Pilot CMS proof', 'Proof of the provisioned CMS', 'active', current_date, current_date + 7, now() - interval '1 day', now() + interval '7 days', '$cms_slug');" \
  "INSERT INTO beneficiary (id, action_id, organization_name, public_description, sort_order) VALUES (gen_random_uuid(), '$cms_action_id', 'Proof beneficiary', 'Proof of the provisioned CMS', 0);" \
  "INSERT INTO action_membership (id, action_id, user_id, role, active_from) VALUES (gen_random_uuid(), '$cms_action_id', '10000000-0000-4000-8000-0000000000c2', 'charity_admin', now() - interval '1 day');" |
  core_sql
cms_proof publish "$cms_action_id" "$cms_slug" "$cms_title"
cms_proof public "$cms_slug" "$cms_title"
# One object written with the CMS's own scoped key: the restore drill must
# bring back the bucket and the RustFS user and policy, not only the SQL.
runtime_compose --profile emdash exec -T campaign-site node --input-type=module -e '
import { createStorage } from "emdash/storage/s3";
await createStorage({}).upload({ key: "restore-drill.txt", body: Buffer.from("restore-drill-media"), contentType: "text/plain" });'

echo "pilot-install-test: restores the CMS from the backup (restore drill)"
leonaid_test pilot-backup --env-file "$env_file" --backup-manifest "$backup_manifest" \
  --password-file "$restic_password_file" --credentials-file "$backup_credentials_file"
assert_cms_backup
restore_project="leonaid-restore-pilot-cms-$suffix"
verify_project_absent "$restore_project"
restore_overlay="$overlay_directory/restore-overlay.yml"
LEONAID_TEST_EXTRA_NETWORKS=mail-egress,crm-admin \
  python3 "$root/tools/surveys/network_override.py" "$overlay_directory/restore-networks.yml"
write_overlay "$overlay_directory/restore-networks.yml" "$restore_overlay"
restore_env_file="$workspace/restore.env"
cp "$env_file" "$restore_env_file"
printf '%s\n' "LEONAID_COMPOSE_PROJECT=$restore_project" \
  "TWENTY_ADMIN_PORT=$restore_admin_port" >>"$restore_env_file"
chmod 600 "$restore_env_file"
restore_compose() {
  docker compose \
    --project-name "$restore_project" \
    --env-file "$restore_env_file" \
    --file "$root/infra/compose/compose.yml" \
    --file "$root/infra/pilot/compose.yml" \
    --file "$restore_overlay" \
    "$@"
}
# A full restore also needs the survey erasure checkpoint (no survey changes
# follow in this proof).
. "$root/tools/backup/survey-recovery-fixture.sh"
prepare_survey_recovery_fixture runtime_compose "$workspace"
restore_owned=true
restore_compose --profile '*' config --format json |
  python3 "$root/tools/testing/reserve_compose_networks.py" "$restore_project" "$restore_overlay"
LEONAID_PILOT_TEST_RESTORE_OVERLAY="$restore_overlay" \
  LEONAID_PILOT_TEST_NETWORKS_PRERESERVED=true \
  leonaid_test pilot-restore \
    --env-file "$env_file" \
    --backup-manifest "$backup_manifest" \
    --target-env-file "$restore_env_file" \
    --password-file "$restic_password_file" \
    --credentials-file "$backup_credentials_file" \
    --confirm "RESTORE:$restore_project" | tee "$workspace/cms-restore.log"
grep -Fq "restore: explicit CMS image identity verified" "$workspace/cms-restore.log"
grep -Fq "cms-recovery: verify-application passed" "$workspace/cms-restore.log"
grep -Fq "pilot-restore: OK:" "$workspace/cms-restore.log"
published=$(restore_compose exec -T core-postgres psql --username leonaid --dbname emdash \
  --tuples-only --no-align \
  --command "SELECT count(*) FROM ec_campaign_pages WHERE status = 'published' AND action_id = '$cms_action_id'")
[ "$published" = 1 ] || {
  echo "pilot-install-test: ERROR: the restored CMS lacks the published page" >&2
  exit 1
}
docker run --rm --network none \
  --volume "${restore_project}_cms-bootstrap-state:/state:ro" "$ALPINE_IMAGE" \
  cat /state/state.json | grep -Fq '"status":"complete"'
# The restored project's CMS answers with its own credentials: database,
# bucket with the scoped key, setup and schema; the media object is back.
restore_compose --profile emdash run --rm --no-deps --entrypoint node \
  campaign-site /app/operator/cms-provision-operator.mjs status \
  >"$workspace/cms-restored-state.txt"
for expected in database=ready storage=ready bootstrap=complete setup=complete schema=ready; do
  grep -qx "$expected" "$workspace/cms-restored-state.txt" || {
    echo "pilot-install-test: ERROR: restored CMS lacks $expected:" >&2
    cat "$workspace/cms-restored-state.txt" >&2
    exit 1
  }
done
restore_compose --profile emdash run --rm --no-deps --entrypoint node \
  campaign-site --input-type=module -e '
import { createStorage } from "emdash/storage/s3";
const file = await createStorage({}).download("restore-drill.txt");
if ((await new Response(file.body).text()) !== "restore-drill-media") process.exit(1);
console.log("restored media object read with the scoped CMS key");'
restore_compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1
verify_owned_project_removed "$restore_project"
restore_owned=false
echo "pilot-install-test: CMS restore drill: published page, media with the scoped key and closed setup grant restored"

echo "pilot-install-test: proves a second first install is refused"
cp "$env_file" "$workspace/second.env"
# The CMS was enabled above; a first install refuses it before the volume
# check, so the second install keeps the install-time setting.
sed -i -e 's/^TWENTY_INTEGRATION_API_KEY=.*/TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL/' \
  -e 's/^LEONAID_CMS_ENABLED=true$/LEONAID_CMS_ENABLED=false/' \
  "$workspace/second.env"
chmod 600 "$workspace/second.env"
expect_refusal "install over an existing project" "already has Docker volumes" \
  --env-file "$workspace/second.env" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$bootstrap_file" --password-file "$restic_password_file"
expect_refusal "install with the provisioned env file" "is not PENDING_PILOT_INSTALL" \
  --env-file "$env_file" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$bootstrap_file" --password-file "$restic_password_file"

echo "pilot-install-test: OK: empty project to verified Twenty admin, provisioned key,"
echo "pilot-install-test:     full stack, first backup, monitoring and Watchdog,"
echo "pilot-install-test:     Twenty and core mail over implicit TLS, scheduled CRM repair,"
echo "pilot-install-test:     CMS provisioned, resumed and repeated, a campaign page published"
echo "pilot-install-test:     on the public host, CMS backups and a CMS restore drill"
