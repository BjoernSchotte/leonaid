CREATE TABLE previous_schema_snapshot (
    id integer PRIMARY KEY,
    label text NOT NULL,
    payload jsonb NOT NULL
);

INSERT INTO previous_schema_snapshot (id, label, payload)
VALUES (
    1,
    'leonaid-core-v0',
    '{"actionId":"20000000-0000-4000-8000-000000000001","amountMinor":7200}'::jsonb
);

INSERT INTO user_account (id, email, display_name, status)
VALUES (
    '10000000-0000-4000-8000-000000000001',
    'system@leonaid.invalid',
    'Legacy System',
    'active'
);

INSERT INTO user_global_role (user_id, role)
VALUES (
    '10000000-0000-4000-8000-000000000001',
    'system_admin'
);

INSERT INTO charity_action (
    id, carrier_name, name, purpose, status, starts_on, ends_on,
    archive_slug, goal_value, actual_value, goal_unit, currency
)
VALUES (
    '20000000-0000-4000-8000-000000000001',
    'Legacy Hilfswerk e.V.',
    'Krapfentaxi Legacy',
    'Realer Upgrade-Nachweis mit einer Alt-Rechnung',
    'active',
    '2026-09-01',
    '2026-11-15',
    'krapfentaxi-legacy',
    7200,
    7200,
    'cent',
    'EUR'
);

INSERT INTO offering (
    id, action_id, code, name, status, unit, allowed_quantity_units,
    pieces_per_unit, unit_price_minor, currency
)
VALUES (
    '70000000-0000-4000-8000-000000000001',
    '20000000-0000-4000-8000-000000000001',
    'legacy-box',
    'Krapfenbox',
    'active',
    'box',
    ARRAY['box']::text[],
    24,
    3600,
    'EUR'
);

INSERT INTO commitment (
    id, action_id, twenty_company_id, source, status, customer_snapshot,
    invoice_recipient_snapshot, currency, total_minor, idempotency_key
)
VALUES (
    '80000000-0000-4000-8000-000000000001',
    '20000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000001',
    'admin',
    'invoiced',
    '{"partyKind":"company","twentyId":"40000000-0000-4000-8000-000000000001","displayName":"Legacy Sponsor GmbH","email":"legacy@leonaid.invalid"}'::jsonb,
    '{"recipientName":"Legacy Sponsor GmbH","streetLine1":"Altweg 7","postalCode":"86150","city":"Augsburg","countryCode":"DE","email":"legacy@leonaid.invalid"}'::jsonb,
    'EUR',
    7200,
    'legacy:commitment:0001'
);

INSERT INTO commitment_line (
    id, commitment_id, offering_id, description_snapshot, quantity,
    unit_snapshot, pieces_per_unit_snapshot, unit_price_minor,
    line_total_minor
)
VALUES (
    '81000000-0000-4000-8000-000000000001',
    '80000000-0000-4000-8000-000000000001',
    '70000000-0000-4000-8000-000000000001',
    'Krapfenbox',
    2,
    'box',
    24,
    3600,
    7200
);

INSERT INTO invoice (
    id, commitment_id, number, status, issued_at, due_on, currency,
    net_minor, tax_minor, gross_minor, recipient_snapshot, line_snapshot,
    tax_note, document_version, idempotency_key
)
VALUES (
    '99000000-0000-4000-8000-000000000001',
    '80000000-0000-4000-8000-000000000001',
    'LEGACY-0001',
    'open',
    '2026-11-16T10:00:00+01:00',
    '2026-11-30',
    'EUR',
    7200,
    0,
    7200,
    '{"recipient":"Legacy Sponsor GmbH","street":"Altweg 7","postalCode":"86150","city":"Augsburg","country":"DE"}'::jsonb,
    '[{"offerId":"70000000-0000-4000-8000-000000000001","quantity":2}]'::jsonb,
    'Legacy-Steuerhinweis',
    1,
    'legacy:invoice:0001'
);
