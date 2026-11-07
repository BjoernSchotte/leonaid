#!/bin/sh
set -eu

root=${1:-$(pwd)}
root=$(cd "$root" && pwd)
. "$root/tools/testing/owned_teardown.sh"
. "$root/infra/locks/images.env"
suffix="$(printf %s "$root" | cksum | cut -d ' ' -f 1)-$$"
project=leonaid-poc021-test-$suffix
owned=false
proof=$(mktemp -d)
isolation_file="$proof/compose-isolation.yml"
compose_file="$root/infra/compose/compose.yml"
env_file="$root/.env.local"

if [ ! -f "$env_file" ]; then
  echo "poc021-test: ERROR: .env.local missing; run ./leonaid bootstrap first" >&2
  exit 1
fi

compose() {
  docker compose \
    --project-name "$project" \
    --env-file "$env_file" \
    --file "$compose_file" \
    --file "$isolation_file" \
    "$@"
}

cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$owned" = true ]; then
    echo "poc021-test: diagnostics for the real core database:" >&2
    compose ps >&2 || true
    compose logs --no-color --tail=100 core-postgres >&2 || true
  fi
  if [ "$owned" = true ]; then
    if ! compose --profile '*' down --volumes --remove-orphans >/dev/null 2>&1; then status=1; fi
    if ! verify_owned_project_removed "$project"; then status=1; fi
    if [ "$status" -eq 0 ]; then echo "test-isolation: $project passed and owned resources were removed"; fi
  fi
  rm -rf "$proof"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

# Refuse existing resources and unreadable inventories before Docker mutations.
existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker volume ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
existing=$(docker network ls -q --filter "label=com.docker.compose.project=$project")
[ -z "$existing" ]
python3 "$root/tools/surveys/network_override.py" "$isolation_file"
owned=true
compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"

docker run --rm \
  -v "$root:/repo:ro" \
  "$PYTHON_IMAGE" \
  python /repo/tools/schema/check_migrations.py /repo/migrations/versions

echo "poc021-test: migrating a fully empty PostgreSQL instance to head"
compose build api
compose up --detach --wait --wait-timeout 120 core-postgres
compose run --rm --no-deps --entrypoint alembic api upgrade head
compose run --rm --no-deps --entrypoint alembic api upgrade head
# Material contracts store real file versions in object storage.
compose up --detach --wait --wait-timeout 120 rustfs
compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/testing/run_python_contracts.py \
    /repo/tools/schema/smoke.py \
    /repo/tools/tasks/schema_contract.py \
    /repo/tools/tasks/service_contract.py \
    /repo/tools/tasks/planning_contract.py \
    /repo/tools/tasks/ordering_contract.py \
    /repo/tools/tasks/structure_contract.py \
    /repo/tools/tasks/http_contract.py \
    /repo/tools/tasks/action_contract.py \
    /repo/tools/materials/schema_contract.py \
    /repo/tools/materials/service_contract.py \
    /repo/tools/materials/member_contract.py \
    /repo/tools/materials/action_contract.py \
    /repo/tools/materials/cleanup_contract.py \
    /repo/tools/materials/http_contract.py \
    /repo/tools/knowledge/schema_contract.py \
    /repo/tools/knowledge/service_contract.py \
    /repo/tools/knowledge/member_contract.py \
    /repo/tools/knowledge/action_contract.py \
    /repo/tools/knowledge/task_contract.py \
    /repo/tools/knowledge/material_contract.py \
    /repo/tools/knowledge/http_contract.py \
    /repo/tools/inbox/schema_contract.py \
    /repo/tools/inbox/submission_contract.py \
    /repo/tools/inbox/case_contract.py \
    /repo/tools/inbox/http_contract.py \
    /repo/tools/inbox/public_contract.py \
    /repo/tools/inbox/task_contract.py \
    /repo/tools/inbox/material_contract.py \
    /repo/tests/integration/test_search_api.py \
    /repo/tests/integration/test_order_cancellation_api.py \
    /repo/tests/integration/test_offline_capture_api.py \
    /repo/tests/integration/test_public_origins_api.py \
    /repo/tests/integration/test_public_campaigns_api.py \
    /repo/tests/integration/test_preferred_surface_service.py

echo "poc021-test: migrating the versioned previous snapshot with its data"
compose --profile '*' down --volumes --remove-orphans
compose --profile '*' config --format json | python3 "$root/tools/testing/reserve_compose_networks.py" "$project" "$isolation_file"
compose up --detach --wait --wait-timeout 120 core-postgres
compose run --rm --no-deps --entrypoint alembic api upgrade 0011_public_orders
compose exec -T core-postgres sh -ec \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  <"$root/tests/fixtures/schema/v0.sql"
# A night-hour invoice from before 0045 proves the invoice-date backfill.
compose run --rm --no-deps --entrypoint alembic api upgrade 0044_inbox
compose exec -T core-postgres sh -ec \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  <"$root/tests/fixtures/schema/night-invoice-0044.sql"
compose run --rm --no-deps --entrypoint alembic api upgrade head
compose run --rm --user "$(id -u):$(id -g)" --no-deps \
  --volume "$root:/repo:ro" \
  --entrypoint python \
  api /repo/tools/schema/smoke.py --legacy

capture_sql() {
  compose exec -T core-postgres sh -ec \
    'psql -v ON_ERROR_STOP=1 -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

echo "poc021-test: 0053 upgrade names existing manual contacts outside the window"
compose run --rm --no-deps --entrypoint alembic api downgrade 0052_commitment_captured_at
printf '%s\n' "INSERT INTO acquisition_activity (id, action_id, occurred_at, channel, outcome, created_at) VALUES ('95300000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000001', CURRENT_TIMESTAMP - interval '20 days', 'phone', 'reached', CURRENT_TIMESTAMP);" | capture_sql
if output=$(compose run --rm --no-deps --entrypoint alembic api upgrade head 2>&1); then
  echo "poc021-test: ERROR: 0053 accepted a manual contact outside the window" >&2
  exit 1
fi
case "$output" in
  *"0053 refused: 1 manual contact(s)"*"95300000-0000-4000-8000-000000000001"*) ;;
  *)
    printf '%s\n' "$output" >&2
    echo "poc021-test: ERROR: 0053 failed for another reason" >&2
    exit 1
    ;;
esac
printf '%s\n' "DELETE FROM acquisition_activity WHERE id = '95300000-0000-4000-8000-000000000001';" | capture_sql
compose run --rm --no-deps --entrypoint alembic api upgrade head
validated=$(printf '%s\n' "SELECT convalidated FROM pg_constraint WHERE conname = 'ck_acquisition_activity_occurred_at_bound';" | capture_sql)
if [ "$validated" != "t" ]; then
  echo "poc021-test: ERROR: 0053 left its check unvalidated: $validated" >&2
  exit 1
fi

echo "poc021-test: 0052 downgrade keeps a queued order without its capture time"
# The legacy order is an admin order; only acquisition orders carry a
# capture time, so it is one for this step and gets its source back after.
legacy_source=$(printf '%s\n' "SELECT source FROM commitment WHERE id = '80000000-0000-4000-8000-000000000001';" | capture_sql)
printf '%s\n' "UPDATE commitment SET source = 'acquisition', captured_at = created_at - interval '1 hour' WHERE id = '80000000-0000-4000-8000-000000000001';" | capture_sql
compose run --rm --no-deps --entrypoint alembic api downgrade 0051_commitment_cancellation
remaining=$(printf '%s\n' "SELECT count(*) FROM commitment WHERE id = '80000000-0000-4000-8000-000000000001'; SELECT count(*) FROM information_schema.columns WHERE table_name = 'commitment' AND column_name = 'captured_at';" | capture_sql | tr '\n' ' ')
if [ "$remaining" != "1 0 " ]; then
  echo "poc021-test: ERROR: 0052 downgrade lost the order or kept the column: $remaining" >&2
  exit 1
fi
compose run --rm --no-deps --entrypoint alembic api upgrade head
printf '%s\n' "UPDATE commitment SET source = '$legacy_source' WHERE id = '80000000-0000-4000-8000-000000000001';" | capture_sql

echo "poc021-test: 0054 keeps Impressum and privacy texts and guards its downgrade"
legal_sql() {
  compose exec -T core-postgres sh -ec \
    'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}
legal_sql <<'SQL'
INSERT INTO legal_configuration_version (
    id, version, legal_name, street_line_1, postal_code, city, country_code,
    tax_identifier, issuer_email, bank_account_holder, iban, bic,
    tax_treatment, tax_rate_basis_points, tax_note, number_prefix,
    number_width, payment_terms_days, public_order_legal_basis,
    public_order_notice_text, consent_text_version, privacy_contact_email,
    invoice_retention_days, commitment_retention_days, contact_retention_days,
    consent_evidence_retention_days, audit_retention_days, e_invoice_decision,
    tax_evidence_id, privacy_evidence_id, e_invoice_evidence_id,
    created_by_user_id, imprint_representatives, imprint_phone,
    imprint_register_court, imprint_register_number
)
VALUES (
    '97700000-0000-4000-8000-000000000052', 9052, 'Schema-Nachweis e. V.',
    'Testweg 52', '86150', 'Augsburg', 'DE', '103/052/00000',
    'schema@leonaid.invalid', 'Schema-Nachweis e. V.',
    'DE89370400440532013000', NULL, 'tax_exempt', 0,
    'Steuerbefreit laut Schema-Nachweis.', 'SN', 5, 14,
    'Vertragserfüllung für den Schema-Nachweis.',
    'Schema-Nachweis: Datenschutzhinweis für die öffentliche Bestellung.',
    'schema-v1', 'datenschutz@leonaid.invalid', 3650, 3650, 730, 3650, 3650,
    'pending', 'STEUER-SCHEMA-052', 'DATENSCHUTZ-SCHEMA-052', NULL,
    '10000000-0000-4000-8000-000000000001',
    'Vorstand: Schema Nachweis', '+49 30 23125 052',
    'Amtsgericht Augsburg', 'VR 0052'
);
SQL
# A register court without number violates the pairing constraint.
if printf '%s\n' "UPDATE legal_configuration_version SET imprint_register_number = NULL WHERE id = '97700000-0000-4000-8000-000000000052';" \
  | legal_sql >/dev/null 2>&1; then
  echo "poc021-test: ERROR: register court without number was stored" >&2
  exit 1
fi
if output=$(compose run --rm --no-deps --entrypoint alembic api \
  downgrade 0053_activity_occurred_at_bound 2>&1); then
  echo "poc021-test: ERROR: downgrade dropped a published Impressum" >&2
  exit 1
fi
case "$output" in
  *"downgrade refused"*) ;;
  *)
    printf '%s\n' "$output" >&2
    echo "poc021-test: ERROR: 0054 downgrade failed for another reason" >&2
    exit 1
    ;;
esac
printf '%s\n' "DELETE FROM legal_configuration_version WHERE id = '97700000-0000-4000-8000-000000000052';" \
  | legal_sql
compose run --rm --no-deps --entrypoint alembic api downgrade 0053_activity_occurred_at_bound
# Versions from before 0054: an "e. V." name gets the registered association
# form, every other name stays without a form (chosen before activation).
legal_sql <<'SQL'
INSERT INTO legal_configuration_version (
    id, version, legal_name, street_line_1, postal_code, city, country_code,
    tax_identifier, issuer_email, bank_account_holder, iban, tax_treatment,
    tax_rate_basis_points, tax_note, number_prefix, number_width,
    payment_terms_days, public_order_legal_basis, public_order_notice_text,
    consent_text_version, privacy_contact_email, invoice_retention_days,
    commitment_retention_days, contact_retention_days,
    consent_evidence_retention_days, audit_retention_days, e_invoice_decision,
    tax_evidence_id, privacy_evidence_id, created_by_user_id
)
SELECT id::uuid, version, legal_name, 'Testweg 52', '86150', 'Augsburg', 'DE',
    '103/052/00000', 'schema@leonaid.invalid', legal_name,
    'DE89370400440532013000', 'tax_exempt', 0,
    'Steuerbefreit laut Schema-Nachweis.', 'SN', 5, 14,
    'Vertragserfüllung für den Schema-Nachweis.',
    'Schema-Nachweis: Datenschutzhinweis für die öffentliche Bestellung.',
    'schema-v1', 'datenschutz@leonaid.invalid', 3650, 3650, 730, 3650, 3650,
    'pending', 'STEUER-SCHEMA-052', 'DATENSCHUTZ-SCHEMA-052',
    '10000000-0000-4000-8000-000000000001'
FROM (VALUES
    ('97700000-0000-4000-8000-000000000053', 9053, 'Förderverein Schema e. V.'),
    ('97700000-0000-4000-8000-000000000054', 9054, 'Lions AG Schema Augsburg')
) AS form_case(id, version, legal_name);
SQL
compose run --rm --no-deps --entrypoint alembic api upgrade head
forms=$(printf '%s\n' "SELECT string_agg(coalesce(legal_form, 'null'), ',' ORDER BY version) FROM legal_configuration_version WHERE version IN (9053, 9054);" \
  | compose exec -T core-postgres sh -ec \
    'psql -v ON_ERROR_STOP=1 -qAt -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
if [ "$forms" != "registered_association,null" ]; then
  echo "poc021-test: ERROR: 0054 legal form backfill is wrong: $forms" >&2
  exit 1
fi
printf '%s\n' "DELETE FROM legal_configuration_version WHERE version IN (9053, 9054);" \
  | legal_sql

echo "poc021-test: 0051 downgrade refuses recorded order cancellations"
cancellation_sql() {
  compose exec -T core-postgres sh -ec \
    'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}
cancellation_sql <<'SQL'
INSERT INTO commitment_cancellation (
    id, action_id, commitment_id, previous_status, reason_snapshot,
    requested_by_user_id, requested_at
)
SELECT '97700000-0000-4000-8000-000000000001', action_id, id, 'review_ready',
    'Schema-Nachweis: Storno bleibt erhalten',
    '10000000-0000-4000-8000-000000000001', CURRENT_TIMESTAMP
FROM commitment WHERE id = '80000000-0000-4000-8000-000000000001';
SQL
if output=$(compose run --rm --no-deps --entrypoint alembic api \
  downgrade 0050_invoice_partial_payments 2>&1); then
  echo "poc021-test: ERROR: downgrade dropped a recorded order cancellation" >&2
  exit 1
fi
case "$output" in
  *"downgrade refused"*) ;;
  *)
    printf '%s\n' "$output" >&2
    echo "poc021-test: ERROR: 0051 downgrade failed for another reason" >&2
    exit 1
    ;;
esac
printf '%s\n' "DELETE FROM commitment_cancellation;" | cancellation_sql
compose run --rm --no-deps --entrypoint alembic api downgrade 0050_invoice_partial_payments
compose run --rm --no-deps --entrypoint alembic api upgrade head

echo "poc021-test: 0055 stores only web or pwa as preferred start area"
# The downgrade target is the revision below this migration, read from the
# file, so a renumbering or a new parent cannot leave the gate behind.
preference_parent=$(sed -n 's/^down_revision: str | None = "\(.*\)"$/\1/p' \
  "$root/migrations/versions/0055_preferred_surface.py")
[ -n "$preference_parent" ] || {
  echo "poc021-test: ERROR: 0055 names no down_revision" >&2
  exit 1
}
preference_sql() {
  compose exec -T core-postgres sh -ec \
    'psql -v ON_ERROR_STOP=1 -q -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}
printf '%s\n' "UPDATE user_account SET preferred_surface = 'pwa' WHERE id = '10000000-0000-4000-8000-000000000001';" | preference_sql
if printf '%s\n' "UPDATE user_account SET preferred_surface = 'crm' WHERE id = '10000000-0000-4000-8000-000000000001';" | preference_sql 2>/dev/null; then
  echo "poc021-test: ERROR: 0055 accepted an unknown start area" >&2
  exit 1
fi
compose run --rm --no-deps --entrypoint alembic api downgrade "$preference_parent"
[ -z "$(printf '%s\n' "SELECT 1 FROM information_schema.columns WHERE table_name = 'user_account' AND column_name = 'preferred_surface';" | preference_sql)" ] || {
  echo "poc021-test: ERROR: 0055 downgrade kept preferred_surface" >&2
  exit 1
}
compose run --rm --no-deps --entrypoint alembic api upgrade head

echo "poc021-test: 0050 downgrade refuses payment data the old schema cannot hold"
payment_guard() {
  compose run --rm --user "$(id -u):$(id -g)" --no-deps \
    --volume "$root:/repo:ro" \
    --entrypoint python \
    api /repo/tools/invoice_settlements/downgrade_guard.py "$@"
}
for scenario in several reversal note partial overpaid; do
  payment_guard seed "$scenario"
  if output=$(compose run --rm --no-deps --entrypoint alembic api \
    downgrade 0049_window_fully_booked 2>&1); then
    echo "poc021-test: ERROR: downgrade accepted payment case $scenario" >&2
    exit 1
  fi
  case "$output" in
    *"downgrade refused"*) ;;
    *)
      printf '%s\n' "$output" >&2
      echo "poc021-test: ERROR: downgrade of case $scenario failed for another reason" >&2
      exit 1
      ;;
  esac
done
payment_guard seed exact
compose run --rm --no-deps --entrypoint alembic api downgrade 0049_window_fully_booked
compose run --rm --no-deps --entrypoint alembic api upgrade head
payment_guard verify-exact

echo "poc021-test: OK: build from empty, upgrade, constraints and data retention proven"
