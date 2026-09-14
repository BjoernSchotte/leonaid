---
title: Eine Core-Migration ergänzen
description: Das Alembic-Schema vorwärts erweitern und gegen reale PostgreSQL-Pfade absichern.
docId: DOC-P034
audience: [dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

1. Lege unter `migrations/versions/` eine Alembic-Revision an, deren
   `down_revision` auf den aktuellen Head zeigt. Bei parallelen Linien ist eine
   explizite Merge-Revision erforderlich.
2. Halte die Revision deterministisch und vorwärtsgerichtet. Core-Migrationen
   greifen nie auf interne Twenty-Tabellen zu.
3. Ergänze die Domain-/Adapteränderung und einen Test gegen echtes PostgreSQL.
   Prüfe den Weg aus leeren Volumes sowie den versionierten vorherigen
   Schema-Stand.
4. Für `drop_table`, `drop_column` oder destruktive Typänderungen sind eine
   ausdrückliche Datenmigration und ein referenzierter Backup-/Restore-Weg
   Pflicht.
5. Führe `./leonaid check` und die betroffenen Integrations- oder Feature-Tests
   aus. Bei Upgradewirkung führe zusätzlich `./leonaid test-upgrade` aus.

Ein Alembic-Exitcode 0 ist notwendig, aber fachliche Verträge und
Fresh-Volume-Recovery geben die Änderung erst vollständig frei.
