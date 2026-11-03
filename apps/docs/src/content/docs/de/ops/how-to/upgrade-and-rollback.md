---
title: Upgrade und Rollback durchführen
description: Gepinnte Core-, Twenty-, RustFS- und EmDash-Versionen mit Wartungsgrenze und geprüftem Rückweg aktualisieren.
docId: DOC-P024
audience: [ops]
diataxis: how-to
contentRevision: 7
reviewedRevision: 7
verifiedAgainst: e222cf15eaacce659fa705321133f151d7e8d63f
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
   Beim Start der Zieldienste erzeugt Compose `core-postgres` und
   `twenty-postgres` mit dem neuen PostgreSQL-Image auf denselben Volumes neu. Ein Minor-Release innerhalb der
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

## RustFS beta.11 auf 1.0.4

RustFS 1.0.4 ist die erste stabile Release-Linie und behebt die curl-,
OpenSSL- und Brotli-Befunde des beta.11-Images. Es läuft auf dem vorhandenen
RustFS-Volume; eine Datenmigration oder ein Export ist nicht nötig. Es liest
die Objekt-, Versions-, Bucket- und IAM-Daten von beta.11 direkt und legt
unter `.rustfs.sys` nur Dateien für Pool-Identität, Bucket-Inkarnation und
Scanner-Zustand an. Die IAM-Migration aus den Release Notes von 1.0 wandelt
MinIO-Daten (`.minio.sys`) um und läuft auf einem RustFS-Volume nicht. Der
Image-Benutzer (UID 10001), der Entrypoint, der Pfad `/data` und die
Umgebungsvariablen, die LeonAid setzt, bleiben unverändert.

`pilot-release` erstellt das Backup, aktiviert den Wartungsmodus und erzeugt
`rustfs` dann mit dem neuen Image neu, bevor Twenty und Core migrieren.
`./leonaid test-upgrade` und `./leonaid test-pilot-release` starten beta.11
mit Golden Data, hashen jede Objektversion vor und nach dem Imagewechsel und
schlagen fehl, wenn sich ein Key, eine Version, ein Delete Marker, ein ETag,
ein Metadateneintrag oder ein SHA-256 unterscheidet. Sie prüfen das zweimal:
im aktualisierten Staging-Projekt und im Produktionsversuch, der aus dem
Recovery Point wiederhergestellt wurde.

Nachdem 1.0.4 auf dem Volume lief, beta.11 nicht wieder starten. Der Rollback
stellt das vollständige RustFS-Volume zusammen mit Core-PostgreSQL aus dem
Recovery Point wieder her.

## EmDash-Kampagnenseite 0.36 auf 1.4

Dieser Abschnitt gilt nur, wenn die optionale Kampagnenseite
(Compose-Profil `emdash`) läuft. EmDash 1.4 bringt die Datenbankmigrationen
`074` bis `091`. Sie ändern vorhandene Inhalte: Migration `079` schreibt jedes
Inhaltsdatum und jeden Revisionsstand in das UTC-ISO-Format um, `080` und `081`
ergänzen eindeutige Indizes und Schreibschutz für Inhalte und Weiterleitungen.
EmDash migriert nicht selbst: Die Kampagnenseite prüft das Schema beim Start
und lehnt eine nicht vollständig migrierte Datenbank ab.

1. Einen Recovery Point mit CMS-Datenbank, Medien-Bucket,
   Verschlüsselungsschlüssel und CMS-Image anlegen und prüfen
   (`./leonaid backup`).
2. Den CMS-Verkehr mit dem bisherigen Image schließen:
   `docker compose … run --rm --no-deps --entrypoint node campaign-site
/app/operator/cms-migration-operator.mjs close`. Die dauerhafte Markierung
   im Volume `cms-bootstrap-state` hält jeden späteren CMS-Prozess geschlossen.
3. Das neue CMS-Image bauen und `campaign-site` daraus neu anlegen, ohne es zu
   starten (`docker compose … up --no-deps --no-start campaign-site`).
4. Den geprüften Controller mit denselben Compose-Dateien wie die Installation
   ausführen: `tools/pilot_release/migrate-cms.sh <Checkout> <Projekt> <Image>
upgrade-emdash <Compose-Dateien…>`. Er prüft die Image-Identität, lehnt eine
   unbekannte oder lückenhafte Migrationshistorie ab, führt den EmDash-eigenen
   Migrator hinter der Verkehrssperre aus und prüft danach das exakte
   Migrationsinventar, die Kampagnenbindungen, den Medienschutz und das
   Kampagnenschema. Ein zweiter Lauf ändert nichts. Danach muss `verify`
   bestehen.
5. Die Kampagnenseiten prüfen. Dann den CMS-Verkehr wieder öffnen, indem die
   Markierung entfernt wird (`docker compose … run --rm --no-deps --entrypoint
rmdir campaign-site /app/bootstrap-state/cms-maintenance`), und
   `campaign-site` starten.

Lehnt der Controller ab oder scheitert eine Migration, bleibt der CMS-Verkehr
geschlossen. Das alte Image nie gegen die teilweise oder vollständig
migrierte Datenbank starten. Stattdessen CMS-SQL, Medien, Schlüssel und Image
aus dem Recovery Point wiederherstellen.
`./leonaid test-emdash-spike --case emdash-upgrade` belegt diesen Weg. Der Test
importiert die echte Krapfentaxi-Kampagne mit EmDash 0.36.0, migriert dieselbe
Datenbank mit diesem Controller, vergleicht jede Inhaltszeile, Revision,
Mediendatei und Bindung vor und nach dem Upgrade und bearbeitet und
veröffentlicht die Seite in drei Browsern.
