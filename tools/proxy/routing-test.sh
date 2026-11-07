#!/bin/sh
# Prove the generated Caddyfiles route every host as specs/multi-domain §6.2
# says: the pilot single-host file, the pilot admin/public split and the dev
# split. Runs the pinned Caddy with the real file (pilot files rendered with
# `tls internal`, nothing else changed) in front of one small Caddy per
# upstream service that answers with its own name and the received path.
# Light enough for ./leonaid check: no product image, no database.
#
# Usage: tools/proxy/routing-test.sh [root]
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/infra/locks/images.env"

suffix="$$-$(date +%s)"
network="leonaid-proxy-routing-$suffix"
work=$(mktemp -d)
containers=""
cleanup() {
  for container in $containers; do
    docker rm -f "$container" >/dev/null 2>&1 || true
  done
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$network-data" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

fail() {
  echo "proxy-routing: ERROR: $*" >&2
  exit 1
}

docker network create --internal "$network" >/dev/null

for service in api web pwa public campaign-site twenty-server mailpit listmonk; do
  case $service in
    campaign-site) reply='campaign-site {uri} xfh={header.X-Forwarded-Host}' ;;
    *) reply="$service {uri}" ;;
  esac
  # Core's on-demand TLS ask (specs/multi-domain §9.1) refuses one name.
  deny=""
  if [ "$service" = api ]; then
    deny='@refused {
		path /internal/tls/ask
		query domain=refused.leonaid.test
	}
	respond @refused 403'
  fi
  cat >"$work/$service.caddy" <<EOF
{
	admin off
	auto_https off
}
:3000, :8000, :8025, :9000 {
	$deny
	respond "$reply" 200
}
EOF
  chmod 0644 "$work/$service.caddy"
  name="leonaid-proxy-routing-$service-$suffix"
  docker run --detach --name "$name" --network "$network" \
    --network-alias "$service" \
    --volume "$work/$service.caddy:/etc/caddy/Caddyfile:ro" \
    "$CADDY_IMAGE" >/dev/null
  containers="$containers $name"
done

run_case() {
  label=$1
  render=$2
  mode=$3
  port=$4
  http_port=$5
  shift 5
  python3 "$root/tools/proxy/caddyfiles.py" --root "$root" --render "$render" \
    --tls-internal >"$work/$label.Caddyfile"
  chmod 0644 "$work/$label.Caddyfile"
  proxy="leonaid-proxy-routing-proxy-$label-$suffix"
  docker volume create "$network-data" >/dev/null
  # shellcheck disable=SC2068 # word splitting of the --env pairs is intended
  # host-write-user: Caddy writes its internal CA into a named volume, no host path
  docker run --detach --name "$proxy" --network "$network" \
    --network-alias proxy \
    --env LEONAID_HTTPS_PORT="$port" \
    $@ \
    --volume "$work/$label.Caddyfile:/etc/caddy/Caddyfile:ro" \
    --volume "$network-data:/data" \
    "$CADDY_IMAGE" >/dev/null
  containers="$containers $proxy"
  ca=/data/caddy/pki/authorities/local/root.crt
  tries=0
  until docker exec "$proxy" test -s "$ca" 2>/dev/null; do
    tries=$((tries + 1))
    [ "$tries" -lt 60 ] || {
      docker logs "$proxy" 2>&1 | tail -20 >&2
      fail "$label: Caddy did not create its internal CA"
    }
    sleep 0.5
  done
  if ! docker run --rm --network "$network" \
    --env ROUTING_CA_FILE="$ca" --env ROUTING_PORT="$port" \
    --env ROUTING_HTTP_PORT="$http_port" \
    --volume "$network-data:/data:ro" \
    --volume "$root/tools/proxy/routing_proof.py:/proof/routing_proof.py:ro" \
    "$PYTHON_IMAGE" python /proof/routing_proof.py "$mode"; then
    docker logs "$proxy" 2>&1 | grep '"level":"error"' | tail -20 >&2 || true
    fail "$label: routes differ from the host routing table"
  fi
  docker rm -f "$proxy" >/dev/null
  docker volume rm "$network-data" >/dev/null
}

run_case pilot-single pilot-single single 443 80 \
  --env LEONAID_PUBLIC_DOMAIN=single.leonaid.test \
  --env CADDY_ACME_EMAIL=operator@leonaid.invalid
run_case pilot-split pilot-split split 443 80 \
  --env LEONAID_ADMIN_DOMAIN=app.leonaid.test \
  --env LEONAID_PUBLIC_DOMAIN=leonaid.test \
  --env "LEONAID_PUBLIC_DOMAIN_ALIASES=www.leonaid.test" \
  --env CADDY_ACME_EMAIL=operator@leonaid.invalid
run_case pilot-admin-only pilot-admin-only admin-only 443 80 \
  --env LEONAID_ADMIN_DOMAIN=app.leonaid.test \
  --env CADDY_ACME_EMAIL=operator@leonaid.invalid
run_case dev-split dev-split split 8443 8080 \
  --env LEONAID_ADMIN_DOMAIN=app.leonaid.test \
  --env LEONAID_PUBLIC_DOMAIN=leonaid.test
echo "proxy-routing: OK: pilot single-host, split, admin-only and dev split routing proven, campaign hosts included"
