# Core migrations

Current bilingual contributor guide:
[Deutsch](../apps/docs/src/content/docs/de/dev/how-to/add-migration.md) ·
[English](../apps/docs/src/content/docs/en/dev/how-to/add-migration.md).

Alembic is the sole owner of the productive LeonAid Core schema.

- Every revision must run forward from the previous revision to `head`.
- `drop_table`, `drop_column` or destructive type changes are allowed only
  together with an explicit data migration and a referenced backup/restore
  procedure.
- Migrations never access internal Twenty tables.
- Tests run every revision against real PostgreSQL from empty volumes and
  against the versioned previous schema snapshot.
