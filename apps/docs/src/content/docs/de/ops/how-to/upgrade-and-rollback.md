---
title: Upgrade und Rollback durchführen
description: Gepinnte Core-, Twenty- und RustFS-Versionen mit Wartungsgrenze und geprüftem Rückweg aktualisieren.
docId: DOC-P024
audience: [ops]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: ee30ab95b4f0c45d863c5e09fa12783583a3475f
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
   Führe danach `infra/upgrade/twenty-queue-store.sh migrate` aus (Teil von
   `pilot-release`). Es arbeitet die Queues eines Redis-7.4-Speichers mit dem
   alten Twenty-Worker ab und leert das Volume, weil Valkey es nicht laden kann.
3. Aktualisiere RustFS und starte Twenty einmal für seine Voraussetzungen.
   Compose erzeugt `core-postgres` und `twenty-postgres` mit dem neuen
   PostgreSQL-Image auf denselben Volumes neu. Ein Minor-Release innerhalb der
   Hauptversion 16 behält das Datenformat; Dump oder `pg_upgrade` entfallen.
   `./leonaid test-upgrade` weist das ab dem vorherigen gepinnten Release nach.
4. Stoppe Twenty Server und führe dessen offizielle Befehle
   `command:prod run-instance-commands` und `command:prod upgrade` über den
   gepinnten Compose-Service aus. Beide müssen Exitcode 0 liefern.
5. Wende das deklarierte Twenty-Schema mit `tools/twenty/provision.py apply`
   (lokal `./leonaid provision-twenty`) an, bevor Core startet. Core schreibt
   und liest das provisionierte CRM-Feld für den Match-Schlüssel; ohne dieses
   Feld scheitern CRM-Schreibzugriffe.
6. Befülle die CRM-Match-Schlüssel bestehender Firmen und Personen mit
   `python -m leonaid.entrypoints.crm_match_keys` im Core-Image (lokal
   `./leonaid repair-crm-match-keys`). Der Lauf ist idempotent und ändert nur
   Datensätze, deren gespeicherter Schlüssel nicht zum Namen passt.
7. Migriere Core explizit, starte die Dienste und prüfe Images, Schemata,
   Healthchecks, Golden-Contract und Browser-Journey.
8. Deaktiviere die Wartung erst nach diesen Nachweisen.

Nach der ersten Schemaänderung bedeutet Rollback Restore: Starte kein älteres
Image gegen eine vorwärts migrierte Datenbank. Halte die Schreibsperre aktiv,
stoppe das fehlerhafte Projekt und stelle denselben Recovery Point in ein neues,
explizit bestätigtes Projekt wieder her. Redis 7.4 kann auch die Datendateien
von Valkey nicht lesen; ein älteres Release startet deshalb nie auf einem
migrierten Queue-Volume, das restaurierte Projekt beginnt mit einem leeren.

## Twenty 2.24 auf 2.54

Twenty 2.54 schließt mehrere Sicherheitslücken, darunter eine Übernahme von
Einladungen ohne Anmeldung in Versionen bis 2.47. Seine Upgrade-Sequenz
enthält jeden Instanz- und Workspace-Befehl seit 1.21, deshalb migriert
`command:prod upgrade` eine 2.24-Datenbank in einem Schritt; ein
Zwischenrelease ist nicht nötig. `./leonaid test-upgrade` beweist genau diesen
Sprung mit Golden Data. Twenty 2.54 entfernt die Spalte `isCustom` der Views
und baut Indizes und Fremdschlüsselprüfungen einer Schemaänderung jetzt in
Hintergrundjobs. Bis diese fertig sind, lehnt es weitere Schemaänderungen ab;
`tools/twenty/provision.py` wartet und wiederholt die abgelehnte Anfrage. Die
Umgebungsvariablen, die LeonAid setzt, bleiben unverändert.
