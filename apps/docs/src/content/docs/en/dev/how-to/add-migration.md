---
title: Add a Core migration
description: Extend the Alembic schema forward and protect it with real PostgreSQL paths.
docId: DOC-P034
audience: [dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

1. Add an Alembic revision under `migrations/versions/` whose `down_revision`
   points to the current head. Parallel histories require an explicit merge
   revision.
2. Keep the revision deterministic and forward-only. Core migrations never
   access internal Twenty tables.
3. Add the domain or adapter change and a test against real PostgreSQL. Verify
   both empty volumes and the versioned previous schema state.
4. `drop_table`, `drop_column`, or destructive type changes require an explicit
   data migration and a referenced backup/restore path.
5. Run `./leonaid check` and affected integration or feature tests. Also run
   `./leonaid test-upgrade` when the change affects upgrades.

Alembic exit zero is necessary, but domain contracts and fresh-volume recovery
provide the complete acceptance evidence.
