-- An invoice issued at 23:30 UTC (00:30 the next day in Berlin) before the
-- invoice date was stored. Applied at revision 0044_inbox on the migrated
-- previous snapshot; 0045 must backfill its UTC day (16 November), which the
-- old code printed and computed the due date from, not the Berlin day.
CREATE TEMP TABLE night_commitment AS
SELECT * FROM commitment WHERE id = '80000000-0000-4000-8000-000000000001';
UPDATE night_commitment SET id = '80000000-0000-4000-8000-0000000000e1';
INSERT INTO commitment SELECT * FROM night_commitment;

CREATE TEMP TABLE night_invoice AS
SELECT * FROM invoice WHERE number = 'LEGACY-0001';
UPDATE night_invoice
SET id = '99000000-0000-4000-8000-0000000000e1',
    commitment_id = '80000000-0000-4000-8000-0000000000e1',
    number = 'LEGACY-0002',
    payment_reference = 'LEGACY-0002',
    idempotency_key = 'schema:night-invoice',
    issued_at = '2026-11-16T23:30:00Z',
    due_on = '2026-11-30';
INSERT INTO invoice SELECT * FROM night_invoice;
