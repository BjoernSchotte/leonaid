#!/bin/sh
set -eu

root=$1
shift
. "$root/infra/locks/images.env"
test_case=all
if [ "$#" -ne 0 ]; then
  if [ "$#" -ne 2 ] || [ "$1" != --case ]; then
    echo "emdash-spike: expected --case <name>; see ./leonaid help" >&2
    exit 2
  fi
  test_case=$2
fi
case "$test_case" in
  krapfentaxi-source|krapfentaxi-migration|krapfentaxi-orders|alias-namespaces|alias-persistence|alias-commands) ;;
  campaign-public-content|campaign-public-http|campaign-public-media|postgres-pool|public-order-component|order-ingress-pilot|campaign-orders) ;;
  all|dependencies|closed-runtime|postgres|rustfs|service-runtime|proxy-routing|identity-profile|identity-map|core-auth|auth-runtime|bootstrap-runtime|admin-browser|authorization-inventory|authorization-surface|campaign-content|campaign-runtime|schema-runtime|schema-migration|campaign-auth-race|campaign-editorial-isolation|campaign-media-binding|campaign-media-upload|campaign-media-http|campaign-editor-pointer|campaign-core-public) ;;
  *) echo "emdash-spike: case not implemented: $test_case" >&2; exit 2 ;;
esac
if [ "$test_case" = alias-commands ] || [ "$test_case" = all ]; then
  /bin/sh "$root/tools/emdash_spike/alias-namespaces-test.sh" "$root" commands
fi
if [ "$test_case" = alias-persistence ] || [ "$test_case" = all ]; then
  /bin/sh "$root/tools/emdash_spike/alias-namespaces-test.sh" "$root" persistence
fi
if [ "$test_case" = alias-namespaces ] || [ "$test_case" = all ]; then
  /bin/sh "$root/tools/emdash_spike/alias-namespaces-test.sh" "$root"
fi
if [ "$test_case" = krapfentaxi-orders ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" migration true
fi
if [ "$test_case" = krapfentaxi-migration ] || [ "$test_case" = all ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" migration
fi
if [ "$test_case" = krapfentaxi-source ] || [ "$test_case" = all ]; then
  docker run --rm --network none --volume "$root:/workspace:ro" --workdir /workspace \
    "$NODE_IMAGE" node tools/emdash_spike/krapfentaxi-source-proof.mjs
fi
if [ "$test_case" = campaign-orders ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" public-http true
fi
if [ "$test_case" = order-ingress-pilot ] || [ "$test_case" = all ]; then
  for config in Caddyfile Caddyfile.test; do
    /bin/sh "$root/tools/emdash_spike/order-ingress-pilot-test.sh" "$root" "$config"
  done
fi
if [ "$test_case" = public-order-component ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" order-component
fi
if [ "$test_case" = postgres-pool ]; then
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" pool
fi
if [ "$test_case" = campaign-public-media ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" public-media
fi

if [ "$test_case" = campaign-public-http ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" public-http
fi

if [ "$test_case" = campaign-public-content ]; then
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" public
fi

if [ "$test_case" = campaign-auth-race ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" race
fi
if [ "$test_case" = campaign-editorial-isolation ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" isolation
fi

if [ "$test_case" = all ] || [ "$test_case" = authorization-inventory ] || [ "$test_case" = authorization-surface ]; then
  docker run --rm --network none --workdir /workspace \
    --volume "$root/tools:/workspace/tools:ro" \
    --volume "$root/node_modules:/workspace/node_modules:ro" \
    --volume "$root/specs/emdash-campaign-microsite-spike:/workspace/specs/emdash-campaign-microsite-spike:ro" \
    "$BUN_IMAGE" bun tools/emdash_spike/authorization-inventory.ts
fi

if [ "$test_case" = all ] || [ "$test_case" = dependencies ]; then
  docker run --rm --network none \
    --volume "$root:/workspace:ro" --workdir /workspace \
    "$NODE_IMAGE" node tools/emdash_spike/dependencies.mjs
fi
if [ "$test_case" = all ] || [ "$test_case" = closed-runtime ]; then
  proof=$(mktemp -d)
  cleanup() {
    rm -f "$proof/image"
    rmdir "$proof"
  }
  trap cleanup EXIT
  trap 'exit 130' HUP INT TERM
  # No shared tag, Compose project, host port, external network or named volume.
  # The image ID file belongs exclusively to this invocation.
  docker build --iidfile "$proof/image" \
    --file "$root/infra/compose/Dockerfile.campaign-site" "$root"
  image=$(cat "$proof/image")
  docker run --rm --network none \
    --volume "$root/tools/emdash_spike/closed-runtime.mjs:/proof/test.mjs:ro" \
    "$image" node /proof/test.mjs
fi
if [ "$test_case" = all ] || [ "$test_case" = postgres ]; then
  /bin/sh "$root/tools/emdash_spike/postgres-test.sh" "$root"
fi
if [ "$test_case" = all ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" public-http true
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" order-component
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" pool
  /bin/sh "$root/tools/emdash_spike/rustfs-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/service-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/proxy-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/identity-profile-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/identity-map-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/core-auth-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" bootstrap
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" browser
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" surface
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" schema
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" schema-migration
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" schema-migration-v2
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" public
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" media
  /bin/sh "$root/tools/emdash_spike/campaign-media-upload-test.sh" "$root"
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" media
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" content
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" public-http
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" isolation
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" public-media
  echo "emdash-spike: INCOMPLETE: database, auth, isolation, rendering and recovery gates are pending" >&2
  exit 2
fi
if [ "$test_case" = rustfs ]; then
  /bin/sh "$root/tools/emdash_spike/rustfs-test.sh" "$root"
fi
if [ "$test_case" = service-runtime ]; then
  /bin/sh "$root/tools/emdash_spike/service-test.sh" "$root"
fi
if [ "$test_case" = proxy-routing ]; then
  /bin/sh "$root/tools/emdash_spike/proxy-test.sh" "$root"
fi
if [ "$test_case" = identity-profile ]; then
  /bin/sh "$root/tools/emdash_spike/identity-profile-test.sh" "$root"
fi
if [ "$test_case" = identity-map ]; then
  /bin/sh "$root/tools/emdash_spike/identity-map-test.sh" "$root"
fi
if [ "$test_case" = core-auth ]; then
  /bin/sh "$root/tools/emdash_spike/core-auth-test.sh" "$root"
fi
if [ "$test_case" = auth-runtime ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root"
fi
if [ "$test_case" = bootstrap-runtime ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" bootstrap
fi
if [ "$test_case" = admin-browser ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" browser
fi
if [ "$test_case" = authorization-surface ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" surface
fi
if [ "$test_case" = campaign-content ]; then
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root"
fi
if [ "$test_case" = schema-runtime ]; then
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" schema
fi
if [ "$test_case" = schema-migration ]; then
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" schema-migration
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" schema-migration-v2
fi
if [ "$test_case" = campaign-media-binding ]; then
  /bin/sh "$root/tools/emdash_spike/campaign-content-test.sh" "$root" media
fi
if [ "$test_case" = campaign-media-upload ]; then
  /bin/sh "$root/tools/emdash_spike/campaign-media-upload-test.sh" "$root"
fi
if [ "$test_case" = campaign-media-http ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" media
fi
if [ "$test_case" = campaign-editor-pointer ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" media-editor
fi
if [ "$test_case" = campaign-core-public ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" core-public
fi
if [ "$test_case" = campaign-runtime ]; then
  /bin/sh "$root/tools/emdash_spike/auth-runtime-test.sh" "$root" content
fi
