#!/bin/sh
# Sourced only after isolated Twenty provisioning and Core key activation.
mkdir "$proof/native-order-deadline"
native_deadline_name="${project}-native-order-deadline"
native_deadline_service=api
compose run --rm --no-deps --name "$native_deadline_name" \
  --volume "$root:/repo:ro" --volume "$proof/native-order-deadline:/proof" \
  --user "$(id -u):$(id -g)" --env LEONAID_ENV=test \
  --env PYTHONPATH=/repo:/workspace/src --entrypoint python api \
  /repo/tools/emdash_spike/native_order_deadline.py &
native_deadline_pid=$!
compose run --rm --no-deps --volume "$proof/native-order-deadline:/proof" \
  --volume "$visual_proof:/visual-proof" admin-browser \
  node tools/emdash_spike/campaign-orders-browser-proof.mjs --imported --native-deadline
wait "$native_deadline_pid"
native_deadline_pid=
echo "native-order-deadline: three native browsers passed actual Core timeout and unchanged-command recovery with independent Core/Twenty verification"
native_deadline_name="${project}-partial-crm-order"
native_deadline_service=partial-order-operator
compose run --rm --no-deps --name "$native_deadline_name" \
  --volume "$proof/native-order-deadline:/proof" --user "$(id -u):$(id -g)" \
  partial-order-operator &
native_deadline_pid=$!
compose run --rm --no-deps --volume "$proof/native-order-deadline:/proof" \
  --volume "$visual_proof:/visual-proof" admin-browser \
  node tools/emdash_spike/campaign-orders-browser-proof.mjs --imported --partial-crm
wait "$native_deadline_pid"
native_deadline_pid=
echo "partial-crm-order: three native browsers passed real partial Twenty write recovery and exact replay"
