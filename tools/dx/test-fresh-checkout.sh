#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
checkout="$tmp/leonaid"
mkdir -p "$checkout"

git -C "$root" checkout-index --all --prefix="$checkout/"
git -C "$checkout" init -q
git -C "$checkout" config user.email "dx-proof@leonaid.invalid"
git -C "$checkout" config user.name "LeonAid DX Proof"
git -C "$checkout" add .
git -C "$checkout" commit -qm "fresh staged checkout"

if "$checkout/leonaid" doctor >"$tmp/pre-bootstrap-doctor.out" 2>&1; then
  echo "dx-proof: ERROR: doctor unexpectedly accepted an unbootstrapped checkout" >&2
  exit 1
fi
for diagnosis in \
  ".env.local fehlt" \
  "Python-Umgebung fehlt" \
  "Frontend-Pakete fehlen" \
  "./leonaid bootstrap"; do
  if ! grep -F "$diagnosis" "$tmp/pre-bootstrap-doctor.out" >/dev/null; then
    echo "dx-proof: ERROR: doctor missed actionable diagnosis '$diagnosis'" >&2
    cat "$tmp/pre-bootstrap-doctor.out" >&2
    exit 1
  fi
done

"$checkout/leonaid" bootstrap
secret_before=$(docker run --rm \
  -v "$checkout:/workspace:ro" \
  "$ALPINE_IMAGE" \
  sha256sum /workspace/.env.local | awk '{print $1}')
"$checkout/leonaid" bootstrap
secret_after=$(docker run --rm \
  -v "$checkout:/workspace:ro" \
  "$ALPINE_IMAGE" \
  sha256sum /workspace/.env.local | awk '{print $1}')
if [ "$secret_before" != "$secret_after" ]; then
  echo "dx-proof: ERROR: repeated bootstrap overwrote local secrets" >&2
  exit 1
fi
"$checkout/leonaid" doctor
"$checkout/leonaid" check
docker run --rm \
  -v "$checkout:/workspace:ro" \
  "$PYTHON_IMAGE" \
  python /workspace/tools/dx/verify_secrets.py \
  /workspace/.env.example /workspace/.env.local

for reservation in \
  "test-e2e:POC-041" \
  "seed:POC-012" \
  "reset:POC-012"; do
  command_name=${reservation%%:*}
  task=${reservation##*:}
  if "$checkout/leonaid" "$command_name" >"$tmp/$command_name.out" 2>&1; then
    echo "dx-proof: ERROR: reserved command $command_name reported false success" >&2
    exit 1
  fi
  if ! grep -F "$task" "$tmp/$command_name.out" >/dev/null; then
    echo "dx-proof: ERROR: reserved command $command_name did not name $task" >&2
    cat "$tmp/$command_name.out" >&2
    exit 1
  fi
done

printf '\nDX dirty-tree proof\n' >>"$checkout/README.md"
if "$checkout/leonaid" check >"$tmp/dirty.out" 2>&1; then
  echo "dx-proof: ERROR: dirty checkout unexpectedly passed check" >&2
  exit 1
fi
if ! grep -F "Arbeitsbaum ist nicht sauber" "$tmp/dirty.out" >/dev/null; then
  echo "dx-proof: ERROR: dirty checkout lacked actionable diagnosis" >&2
  cat "$tmp/dirty.out" >&2
  exit 1
fi

echo "dx-proof: OK: fresh bootstrap/doctor/check and dirty-tree rejection"
