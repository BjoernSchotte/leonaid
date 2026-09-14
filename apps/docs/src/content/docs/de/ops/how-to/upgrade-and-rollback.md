---
title: Upgrade und Rollback durchführen
description: Gepinnte Core-, Twenty- und RustFS-Versionen mit Wartungsgrenze und geprüftem Rückweg aktualisieren.
docId: DOC-P024
audience: [ops]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Aktualisiere zuerst `infra/locks/external-systems.lock`,
`infra/locks/images.env` und `infra/upgrade/compatibility-matrix.json`. Lies
Release Notes und Migrationen, führe `./leonaid check` und
`./leonaid test-upgrade` aus und protokolliere Wartungsfenster,
Verantwortlichen und einen frischen Recovery Point.

1. Aktiviere `infra/upgrade/maintenance.sh enable` und prüfe, dass Schreibzugriffe
   mit `503 maintenance_mode` und `Retry-After` abgewiesen werden.
2. Erzeuge und prüfe ein verschlüsseltes Backup.
3. Aktualisiere RustFS und starte Twenty einmal für seine Voraussetzungen.
4. Stoppe Twenty Server und führe dessen offizielle Befehle
   `command:prod run-instance-commands` und `command:prod upgrade` über den
   gepinnten Compose-Service aus. Beide müssen Exitcode 0 liefern.
5. Migriere Core explizit, starte die Dienste und prüfe Images, Schemata,
   Healthchecks, Golden-Contract und Browser-Journey.
6. Deaktiviere die Wartung erst nach diesen Nachweisen.

Nach der ersten Schemaänderung bedeutet Rollback Restore: Starte kein älteres
Image gegen eine vorwärts migrierte Datenbank. Halte die Schreibsperre aktiv,
stoppe das fehlerhafte Projekt und stelle denselben Recovery Point in ein neues,
explizit bestätigtes Projekt wieder her.
