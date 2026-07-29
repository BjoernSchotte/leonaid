#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

project=${LEONAID_PILOT_BACKUP_PROJECT:-leonaid-pilot041-s3}
network="${project}_offsite"
volume="${project}_rustfs-data"
container="${project}-rustfs"
bucket=leonaid-pilot041-restic
repository="s3:http://backup-rustfs:9000/$bucket"
source_project=leonaid-production-test
workspace=$(mktemp -d)
password_file="$workspace/restic-password"
wrong_password_file="$workspace/wrong-password"
credentials_file="$workspace/s3.env"
payload="$workspace/payload"
restored="$workspace/restored"
incomplete="$workspace/incomplete"
rotated_access=pilot-backup-rotated-access-002
rotated_secret=pilot-backup-rotated-secret-002

cleanup() {
  status=$?
  docker rm --force "$container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  rm -rf "$workspace"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

wait_for_rustfs() {
  attempts=0
  while [ "$attempts" -lt 60 ]; do
    health=$(docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null || true)
    if [ "$health" = "healthy" ]; then
      return
    fi
    attempts=$((attempts + 1))
    sleep 1
  done
  echo "pilot-backup-test: ERROR: externes RustFS wurde nicht bereit" >&2
  exit 1
}

write_credentials() {
  access_key=$1
  secret_key=$2
  docker run --rm \
    --env "AWS_ACCESS_KEY_ID=$access_key" \
    --env "AWS_SECRET_ACCESS_KEY=$secret_key" \
    --volume "$workspace:/proof" \
    "$PYTHON_IMAGE" \
    python -c 'import os,pathlib
pathlib.Path("/proof/s3.env").write_text(
  "AWS_ACCESS_KEY_ID="+os.environ["AWS_ACCESS_KEY_ID"]+"\n"
  "AWS_SECRET_ACCESS_KEY="+os.environ["AWS_SECRET_ACCESS_KEY"]+"\n"
  "AWS_DEFAULT_REGION=us-east-1\n"
  "AWS_REGION=us-east-1\n",
  encoding="utf-8",
)'
  chmod 600 "$credentials_file"
}

start_rustfs() {
  access_key=$1
  secret_key=$2
  docker run --detach \
    --name "$container" \
    --network "$network" \
    --network-alias backup-rustfs \
    --label "com.docker.compose.project=$project" \
    --env "RUSTFS_ACCESS_KEY=$access_key" \
    --env "RUSTFS_SECRET_KEY=$secret_key" \
    --volume "$volume:/data" \
    --health-cmd 'curl --fail http://localhost:9000/health' \
    --health-interval 2s \
    --health-timeout 2s \
    --health-retries 30 \
    "$RUSTFS_IMAGE" /data >/dev/null
  wait_for_rustfs
}

restic_run() {
  password_path=$1
  shift
  docker run --rm \
    --network "$network" \
    --env-file "$credentials_file" \
    --env "RESTIC_REPOSITORY=$repository" \
    --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
    --volume "$password_path:/run/secrets/restic-password:ro" \
    --volume "$workspace:/proof" \
    "$RESTIC_IMAGE" "$@"
}

restic_timeout_run() {
  timeout_seconds=$1
  shift
  docker run --rm \
    --network "$network" \
    --env-file "$credentials_file" \
    --env "RESTIC_REPOSITORY=$repository" \
    --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
    --volume "$password_file:/run/secrets/restic-password:ro" \
    --volume "$workspace:/proof" \
    --entrypoint /usr/bin/timeout \
    "$RESTIC_IMAGE" "$timeout_seconds" /usr/bin/restic "$@"
}

docker rm --force "$container" >/dev/null 2>&1 || true
docker network rm "$network" >/dev/null 2>&1 || true
docker volume rm "$volume" >/dev/null 2>&1 || true
docker network create \
  --label "com.docker.compose.project=$project" \
  "$network" >/dev/null
docker volume create \
  --label "com.docker.compose.project=$project" \
  "$volume" >/dev/null

access_key=pilot-backup-initial-access-001
secret_key=pilot-backup-initial-secret-001
write_credentials "$access_key" "$secret_key"
docker run --rm \
  --volume "$workspace:/proof" \
  "$PYTHON_IMAGE" \
  python -c 'import pathlib,secrets
pathlib.Path("/proof/restic-password").write_text(secrets.token_urlsafe(48)+"\n")
pathlib.Path("/proof/wrong-password").write_text(secrets.token_urlsafe(48)+"\n")'
chmod 600 "$password_file" "$wrong_password_file"
start_rustfs "$access_key" "$secret_key"

docker run --rm \
  --network "$network" \
  --env "AWS_ACCESS_KEY_ID=$access_key" \
  --env "AWS_SECRET_ACCESS_KEY=$secret_key" \
  --volume "$root:/workspace:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  /workspace/.venv/bin/python -c "import boto3
s3=boto3.client(
  's3',
  endpoint_url='http://backup-rustfs:9000',
  aws_access_key_id='$access_key',
  aws_secret_access_key='$secret_key',
  region_name='us-east-1',
)
s3.create_bucket(Bucket='$bucket')"

mkdir -p "$payload" "$incomplete"
docker run --rm \
  --env "BACKUP_SOURCE_PROJECT=$source_project" \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$workspace:/proof" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python -c 'import datetime,hashlib,json,os,pathlib
p=pathlib.Path("/proof/payload")
files={}
for index,name in enumerate(("core.dump","twenty.dump","twenty-storage.tar","rustfs-data.tar"),1):
    data=(f"pilot-recovery-part-{index}\n").encode()
    (p/name).write_bytes(data)
    files[name]={"sha256":hashlib.sha256(data).hexdigest(),"size":len(data)}
(p/"manifest.json").write_text(json.dumps({
  "schemaVersion":1,
  "createdAt":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "sourceProject":os.environ["BACKUP_SOURCE_PROJECT"],
  "files":files,
},sort_keys=True)+"\n",encoding="utf-8")
pathlib.Path("/proof/incomplete/core.dump").write_bytes(b"incomplete")'

restic_run "$password_file" init
restic_run "$password_file" backup \
  --host "$source_project" \
  --tag "leonaid-$source_project" \
  /proof/payload
restic_run "$password_file" check --read-data

set +e
wrong_output=$(restic_run "$wrong_password_file" snapshots 2>&1)
wrong_status=$?
set -e
if [ "$wrong_status" -eq 0 ]; then
  echo "pilot-backup-test: ERROR: falsches Restic-Passwort akzeptiert" >&2
  exit 1
fi
if printf '%s' "$wrong_output" | grep -Fq "$secret_key"; then
  echo "pilot-backup-test: ERROR: S3-Secret in Restic-Fehlerausgabe" >&2
  exit 1
fi

docker stop "$container" >/dev/null
set +e
network_output=$(restic_timeout_run 15 snapshots 2>&1)
network_status=$?
set -e
if [ "$network_status" -eq 0 ]; then
  echo "pilot-backup-test: ERROR: Netzwerkunterbrechung blieb unbemerkt" >&2
  exit 1
fi
if printf '%s' "$network_output" | grep -Fq "$secret_key"; then
  echo "pilot-backup-test: ERROR: S3-Secret in Netzwerkfehlerausgabe" >&2
  exit 1
fi
docker start "$container" >/dev/null
wait_for_rustfs

restic_run "$password_file" restore latest \
  --host "$source_project" \
  --tag "leonaid-$source_project" \
  --target /proof/restored
backup_root=$(find "$restored" -type f -name manifest.json -print | head -n 1)
[ -n "$backup_root" ] || {
  echo "pilot-backup-test: ERROR: Restore enthält kein Manifest" >&2
  exit 1
}
backup_root=$(dirname "$backup_root")
docker run --rm \
  --env PYTHONPATH=/workspace \
  --volume "$root:/workspace:ro" \
  --volume "$backup_root:/backup:ro" \
  --workdir /workspace \
  "$PYTHON_IMAGE" \
  python tools/backup/manifest.py /backup \
    --source-project "$source_project"

restic_run "$password_file" backup \
  --host "$source_project" \
  --tag "leonaid-$source_project" \
  /proof/incomplete
rm -rf "$restored"
mkdir -p "$restored"
restic_run "$password_file" restore latest \
  --host "$source_project" \
  --tag "leonaid-$source_project" \
  --target /proof/restored
if find "$restored" -type f -name manifest.json -print | grep -q .; then
  echo "pilot-backup-test: ERROR: unvollständiger Snapshot enthält Manifest" >&2
  exit 1
fi

docker rm --force "$container" >/dev/null
write_credentials "$rotated_access" "$rotated_secret"
start_rustfs "$rotated_access" "$rotated_secret"
restic_run "$password_file" snapshots >/dev/null

echo "pilot-backup-test: OK: echtes S3/Restic, falsches Passwort,"
echo "pilot-backup-test:     Netzunterbrechung, unvollständiger Snapshot und"
echo "pilot-backup-test:     rotierte Zugangsdaten fail-closed bewiesen"
