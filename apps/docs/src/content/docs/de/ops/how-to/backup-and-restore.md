---
title: Sichern und in eine frische Umgebung wiederherstellen
description: LeonAid-Daten verschlüsselt sichern und einen kontrollierten Fresh-Volume-Restore durchführen.
docId: DOC-P023
audience: [ops]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Benötigt werden ein externes Restic-Ziel, eine Passwortdatei und optional eine
Backend-Zugangsdaten-Datei; beide Dateien haben Modus `0600` und liegen
außerhalb von Git und Backup-Repository.

1. Starte für einen Pilotbetrieb `./leonaid pilot-backup --env-file ENV
--backup-manifest MANIFEST --password-file PASSWORD --credentials-file
CREDENTIALS`.
2. Prüfe das erzeugte Manifest und den erfolgreichen `restic check --read-data`.
   Gesichert werden beide PostgreSQL-Datenbanken, Twenty-Dateien und das ganze
   RustFS-Volume. Redis, Mailpit, Images und Klartext-Secrets sind ausgeschlossen.
3. Erstelle für einen Drill ein leeres Projekt namens `leonaid-restore-<name>`
   und ein separates Ziel-Environment mit demselben externen Repository.
4. Starte `./leonaid pilot-restore` mit Quell- und Ziel-Environment,
   Backupmanifest, Secret-Dateien und der exakten Bestätigung
   `--confirm RESTORE:leonaid-restore-<name>`.
5. Prüfe nach dem Restore Healthchecks, Golden-Contract, Dokument-Hashes,
   Sitzungen und Browser-Journey. Gib das Ziel erst danach frei.

Der Restore überschreibt keine bestehende Umgebung. Umfragedaten erfordern
zusätzlich das unabhängig aufbewahrte Löschverzeichnis samt gefordertem
Aktualitätszeitpunkt. Zielwerte des aktuellen PoC-Vertrags sind RPO höchstens
24 Stunden, RTO höchstens zwei Stunden und ein vollständiger Drill mindestens
quartalsweise sowie vor schemaändernden Upgrades.
