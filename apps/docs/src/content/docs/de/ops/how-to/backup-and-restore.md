---
title: Sichern und in eine frische Umgebung wiederherstellen
description: LeonAid-Daten verschlüsselt sichern und einen kontrollierten Fresh-Volume-Restore durchführen.
docId: DOC-P023
audience: [ops]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: ee007bf6c2e21edf0b939ee5641b3a9f98674560
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

Benötigt werden ein externes Restic-Ziel, eine Passwortdatei und optional eine
Backend-Zugangsdaten-Datei; beide Dateien haben Modus `0600` und liegen
außerhalb von Git und Backup-Repository.

1. Starte für einen Pilotbetrieb `./leonaid pilot-backup --env-file ENV
--backup-manifest MANIFEST --password-file PASSWORD --credentials-file
CREDENTIALS`.
2. Prüfe das erzeugte Manifest und den erfolgreichen `restic check --read-data`.
   Gesichert werden beide PostgreSQL-Datenbanken, Twenty-Dateien, das ganze
   RustFS-Volume und im Pilot das Caddy-Datenvolume mit den Zertifikaten und
   dem ACME-Konto jedes Hosts. Ein restaurierter Proxy startet daher ohne neue
   Zertifikatsanfragen, aber nur mit `pilot-restore --with-tls-state`: nutze
   es, wenn du die Installation selbst auf einen neuen Server mit denselben
   Hostnamen zurückspielst. Staging- und Übungsziele bekommen keine
   Produktionsschlüssel und holen eigene Zertifikate. Das Archiv enthält
   private Schlüssel; schütze das Repository-Passwort entsprechend. Der Valkey-Queue-Speicher (`twenty-redis`), Mailpit, Images
   und Klartext-Secrets sind ausgeschlossen. Ein restauriertes Projekt startet
   mit leerem Queue-Speicher; `twenty-server` registriert seine Cron-Jobs neu.
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
