#!/bin/sh
# End-to-end proof of ./leonaid pilot-install against real services in an
# isolated, owned Compose project: real Twenty with e-mail verification, real
# S3/Restic backup target, real TLS proxy, real Prometheus/Alertmanager.
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project="${LEONAID_PILOT_INSTALL_PROJECT:-leonaid-production-test-install}-$suffix"
build_project="leonaid-pilot-install-images-$suffix"
operator_backup_project="leonaid-pilot-install-backup-$suffix"
operator_backup_container="$operator_backup_project-rustfs"
operator_backup_volume="$operator_backup_project-rustfs-data"
operator_backup_bucket=leonaid-pilot-install
set -- $(python3 - "${LEONAID_PILOT_TEST_HTTP_PORT:-0}" \
  "${LEONAID_PILOT_TEST_HTTPS_PORT:-0}" <<'PORTS'
import socket, sys
sockets = []
for value in sys.argv[1:]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", int(value)))
    sockets.append(sock)
print(" ".join(str(sock.getsockname()[1]) for sock in sockets))
PORTS
)
[ "$#" -eq 2 ] || { echo 'pilot-install-test: port allocation failed' >&2; exit 1; }
export LEONAID_PILOT_TEST_HTTP_PORT="$1"
export LEONAID_PILOT_TEST_HTTPS_PORT="$2"
workspace=$(mktemp -d)
mkdir -p "$workspace/evidence" "$root/.artifacts"
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
image_services="api web pwa public survey-validator proxy"
runtime_owned=false
backup_owned=false
build_owned=false

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
    runtime_compose --profile monitoring logs --no-color --tail=60 \
      twenty-server api proxy alertmanager >&2 || true
  fi
  if [ "$runtime_owned" = true ]; then
    runtime_compose --profile monitoring down --volumes --remove-orphans \
      >/dev/null 2>&1 || status=1
    verify_project_absent "$project" || status=1
  fi
  if [ "$backup_owned" = true ]; then
    docker rm --force "$operator_backup_container" >/dev/null 2>&1 || status=1
    docker volume rm "$operator_backup_volume" >/dev/null 2>&1 || status=1
  fi
  if [ "$build_owned" = true ]; then
    for service in $image_services; do
      docker image rm "$build_project-$service:latest" >/dev/null 2>&1 || status=1
    done
    verify_project_absent "$build_project" || status=1
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

for owned in "$project" "$build_project" "$operator_backup_project"; do
  verify_project_absent "$owned"
done

echo "pilot-install-test: builds the six release images"
build_owned=true
docker compose \
  --project-name "$build_project" \
  --env-file "$root/.env.local" \
  --file "$root/infra/compose/compose.yml" \
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
export LEONAID_TEST_CORE_IMAGE LEONAID_TEST_WEB_IMAGE LEONAID_TEST_PWA_IMAGE \
  LEONAID_TEST_PUBLIC_IMAGE LEONAID_TEST_SURVEY_VALIDATOR_IMAGE \
  LEONAID_TEST_PROXY_IMAGE

python3 "$root/tools/surveys/network_override.py" "$overlay_directory/networks.yml"
python3 - "$root/infra/pilot/compose.test.yml" "$overlay_directory/networks.yml" "$overlay" <<'OVERLAY'
from pathlib import Path
import sys
base, network, target = map(Path, sys.argv[1:])
target.write_text(base.read_text() + "\nnetworks:\n" + network.read_text().split("\nnetworks:\n", 1)[1])
OVERLAY

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
  --volume "$workspace:$workspace" \
  "$PYTHON_IMAGE" \
  python -c 'import os, pathlib, secrets, string
w = os.environ["WORKSPACE"]
path = pathlib.Path(w) / "production.env"
values = {
  "LEONAID_COMPOSE_PROJECT": os.environ["PROJECT"],
  "LEONAID_SERVICE_VERSION": "2026.11.1",
  "LEONAID_RELEASE_COMMIT": os.environ["COMMIT"],
  "LEONAID_PUBLIC_DOMAIN": "portal.leonaid.org",
  "LEONAID_PUBLIC_BASE_URL": "https://portal.leonaid.org",
  "LEONAID_ALLOWED_ORIGINS": "https://portal.leonaid.org",
  "TWENTY_PUBLIC_DOMAIN": "crm.leonaid.org",
  "TWENTY_PUBLIC_BASE_URL": "https://crm.leonaid.org",
  "CADDY_ACME_EMAIL": "operations@leonaid.org",
  "RUSTFS_BUCKET": "leonaid-production-club-111",
  "RESTIC_REPOSITORY": os.environ["REPOSITORY"],
  "LEONAID_BACKUP_MANIFEST_PATH": w + "/evidence/latest-backup-manifest.json",
  "LEONAID_MONITORED_DISK_PATH": w,
  "LEONAID_ALERT_WEBHOOK_URL_FILE": w + "/alert-webhook-url",
  "LEONAID_ALERT_HEARTBEAT_URL_FILE": w + "/alert-heartbeat-url",
  "MAIL_HEALTH_URL": "https://portal.leonaid.org/_health",
  "MAIL_SMTP_HOST": "smtp.leonaid.org",
  "MAIL_FROM": "LeonAid <noreply@leonaid.org>",
  "MAIL_ENVELOPE_FROM": "bounces@leonaid.org",
  "MAIL_REPLY_TO": "support@leonaid.org",
  "MAIL_SMTP_USERNAME": "pilot-install-smtp",
  "MAIL_SMTP_PASSWORD": "".join(
    secrets.choice(string.ascii_letters + string.digits) for _ in range(32)
  ),
}
for name in ("CORE", "WEB", "PWA", "PUBLIC", "PROXY", "SURVEY_VALIDATOR"):
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
verify_project_absent "$project" || {
  echo 'pilot-install-test: ERROR: a refused install left resources behind' >&2
  exit 1
}

echo "pilot-install-test: runs pilot-install on the empty project"
runtime_owned=true
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
done

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
assert set(value["files"]) == {"core.dump", "twenty.dump", "twenty-storage.tar", "rustfs-data.tar"}'

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

echo "pilot-install-test: proves a second first install is refused"
cp "$env_file" "$workspace/second.env"
sed -i 's/^TWENTY_INTEGRATION_API_KEY=.*/TWENTY_INTEGRATION_API_KEY=PENDING_PILOT_INSTALL/' \
  "$workspace/second.env"
chmod 600 "$workspace/second.env"
expect_refusal "install over an existing project" "already has Docker volumes" \
  --env-file "$workspace/second.env" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$bootstrap_file" --password-file "$restic_password_file"
expect_refusal "install with the provisioned env file" "is not PENDING_PILOT_INSTALL" \
  --env-file "$env_file" --release-manifest "$release_manifest" \
  --twenty-bootstrap-file "$bootstrap_file" --password-file "$restic_password_file"

echo "pilot-install-test: OK: empty project to verified Twenty admin, provisioned key,"
echo "pilot-install-test:     full stack, first backup, monitoring and Watchdog"
