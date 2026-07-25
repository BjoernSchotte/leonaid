# Core-Migrationen

Alembic ist alleiniger Owner des produktiven LeonAid-Core-Schemas.

- Jede Revision muss vorwärts von der vorherigen Revision auf `head` laufen.
- `drop_table`, `drop_column` oder destruktive Typänderungen sind nur zusammen
  mit einer expliziten Datenmigration und einer referenzierten
  Backup-/Restore-Prozedur zulässig.
- Migrationen greifen niemals auf interne Twenty-Tabellen zu.
- Tests führen jede Revision gegen echtes PostgreSQL aus leeren Volumes und
  gegen den versionierten vorherigen Schema-Snapshot aus.
