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

## Pins und Schwachstellenbefunde prüfen

Renovate (`renovate.json`) öffnet jeden Montag gebündelte Update-PRs für
Container-Images, `uv.lock`, `bun.lock` und die Digests der GitHub Actions.
Sicherheitskorrekturen kommen sofort als eigene PRs. Twenty, PostgreSQL, Valkey
und RustFS erhalten eigene PRs mit dem Label `needs-upgrade-runbook`; für sie
gelten die Schritte unten. Nichts wird automatisch gemergt.

`infra/locks/external-systems.lock` hält `reviewedAt` und `nextReviewOn` fest.
`./leonaid check` schlägt fehl, sobald `nextReviewOn` überschritten ist. Für
die erneute Prüfung vergleichst du jeden gepinnten Tag mit dem neuesten
Upstream-Release und den Advisories, aktualisierst ihn oder behältst ihn
bewusst bei und führst `./leonaid check` und `tools/ci/security.sh` aus. Setze
danach `reviewedAt` auf das Prüfdatum und `nextReviewOn` auf höchstens drei
Monate später. Mehr als sechs Monate weist der Checker ab.

Der Security-Job der CI (`tools/ci/security.sh`) blockiert jeden behebbaren
Befund der Stufe HIGH oder CRITICAL:

- Trivy prüft den Checkout, alle LeonAid-Images und jedes Laufzeit-Image von
  Drittanbietern aus `infra/security/image-scan-scope.json`. Jedes System des
  Locks muss dort gescannt oder mit Begründung ausgenommen sein.
- OSV-Scanner prüft `uv.lock` und `bun.lock`.

Gibt es noch keine Korrektur, trage eine Ausnahme in
`infra/security/vulnerability-allowlist.json` ein: Advisory-ID, betroffene
Ziele, Begründung, Prüfer, `reviewedOn` und `expires` (höchstens 90 Tage
später). Eine abgelaufene Ausnahme lässt `./leonaid check` und den
Security-Job scheitern. Aktualisiere dann und lösche die Ausnahme oder prüfe
sie erneut.

## Upgrade

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

## Rollback

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
