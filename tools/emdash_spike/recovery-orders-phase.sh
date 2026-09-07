#!/bin/sh
# Sourced by recovery-app-phase.sh only for the full Twenty/order rehearsal.
recovery_orders_prepare() {
  fixture /repo/tools/emdash_spike/core_auth_fixture.py prepare-mixed-offerings
  compose up --detach --wait --wait-timeout 420 twenty-server twenty-worker
  compose run --rm --no-deps --user "$(id -u):$(id -g)" --volume "$proof:/proof" orders-operator
  TWENTY_INTEGRATION_API_KEY=$(sed -n 's/^TWENTY_INTEGRATION_API_KEY=//p' "$proof/integration.env")
  export TWENTY_INTEGRATION_API_KEY
  if [ "${#TWENTY_INTEGRATION_API_KEY}" -lt 32 ]; then
    echo "recovery-orders: restricted key missing" >&2
    exit 1
  fi
  compose up --no-deps --detach --wait api
  recovery_visual_proof=$(mktemp -d)
  mkdir "$proof/recovery-orders-browser"
  compose run --rm --no-deps --volume "$proof/recovery-orders-browser:/proof" --volume "$recovery_visual_proof:/visual-proof" admin-browser \
    node tools/emdash_spike/campaign-orders-browser-proof.mjs --imported --before-recovery
  cp "$proof/recovery-orders-browser/orders-ui.json" "$proof/orders-ui.json"
  fixture /repo/tools/emdash_spike/campaign_orders_verify.py
  cp "$proof/orders-ui.json" "$proof/pre-recovery-orders.json"
  echo "recovery-orders: 24 actual browser orders and Twenty records verified before backup"
}
recovery_orders_verify() {
  # Never provision, reseed or replace the restricted key on the restored CRM.
  fixture /repo/tools/emdash_spike/campaign_orders_verify.py --before-recovery
  compose run --rm --no-deps --volume "$proof/recovery-orders-browser:/proof" --volume "$recovery_visual_proof:/visual-proof" admin-browser \
    node tools/emdash_spike/campaign-orders-browser-proof.mjs --imported --after-recovery
  cp "$proof/recovery-orders-browser/orders-ui.json" "$proof/orders-ui.json"
  fixture /repo/tools/emdash_spike/campaign_orders_verify.py
  fixture /repo/tools/emdash_spike/campaign_orders_verify.py --before-recovery
  # The target has its own CA; do not accidentally verify against source TLS.
  compose cp proxy:/data/caddy/pki/authorities/local/root.crt "$proof/root.crt" >/dev/null
  LEONAID_ENV=test fixture /repo/tools/emdash_spike/valid_order_ingress_proof.py
  echo "recovery-orders: pre-backup orders preserved, 24 new browser orders converged with restored Twenty, native replay and public Core ingress denial passed"
  echo "recovery-orders: synthetic screenshots retained in $recovery_visual_proof"
}
