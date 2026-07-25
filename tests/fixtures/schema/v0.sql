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
