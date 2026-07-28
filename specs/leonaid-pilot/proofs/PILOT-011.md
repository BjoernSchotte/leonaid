# PILOT-011 – Account sperren, reaktivieren und archivieren

Task-ID: `PILOT-011`

Nachweisdatum: 28. Juli 2026

Status: technisch vollständig bewiesen, formaler Abschluss blockiert

## Ergebnis

Die Kontostatusverwaltung ist als serverseitige FastAPI-/PostgreSQL-Funktion
mit einer geführten System-Admin-Oberfläche umgesetzt:

- Ausschließlich System-Admins mit frisch bestätigter Anmeldung dürfen einen
  Status ändern.
- Sperren, Revisionswechsel, Sitzungsentzug, Audit und Idempotenzbeleg laufen
  atomar in einer Datenbanktransaktion.
- Gesperrte Konten erhalten trotz neutraler HTTP-Antwort keine neue
  Login-Challenge.
- Reaktivieren stellt keine widerrufene Sitzung wieder her.
- Archivieren behält historische Aktionsmitgliedschaften, Aktivitäten,
  AuditEvents, Rechnungen und Dokumentreferenzen.
- Selbstsperre, Selbstarchivierung und die Archivierung des letzten aktiven
  System-Admins werden serverseitig abgelehnt.
- Die Oberfläche nennt vor der Bestätigung die betroffene Person, die konkrete
  Auswirkung und die Anzahl unwiderruflich beendeter Sitzungen.

OpenAPI und der generierte TypeScript-Client enthalten den
revisionsgesicherten, idempotenten Status-Endpunkt.

## Automatische Nachweise

```sh
./leonaid test-unit
/bin/sh tools/schema/test.sh /Users/bjoern/code/leonaid
./leonaid test-identity
/bin/sh tools/ci/lint-types.sh
```

Ergebnis:

```text
169 passed
poc021-test: OK: Leeraufbau, Upgrade, Constraints und Datenhalt bewiesen
identity-contract: Rollen, Statusrevision, Idempotenz, Konkurrenz,
Archivtreue und sofortiger Sitzungsentzug real bewiesen
8 passed in Chromium
identity-test: OK: Mitgliederübersicht, Statusworkflow, Konkurrenz,
Sitzungsentzug und Persona-Navigation real bewiesen
ci-lint-types: OK
```

Der Integrationstest baut echtes PostgreSQL und FastAPI aus leeren Volumes
auf. Er belegt insbesondere:

1. Ablehnung einer veralteten Fresh-Login-Sitzung und einer nicht berechtigten
   Aktionsrolle;
2. atomaren Entzug von genau zwei realen Sitzungen beim Sperren;
3. keine Login-Challenge für das gesperrte Konto;
4. keine Wiederherstellung alter Sitzungen nach Reaktivierung;
5. unveränderte Summen historischer Fachreferenzen vor und nach Archivierung;
6. genau einen Gewinner bei zwei konkurrierenden, widersprüchlichen
   Statusänderungen;
7. genau einen vollständigen Audit- und Idempotenzbeleg je erfolgreichem
   Kommando.

Ein Unit-Regressionsbeleg prüft zusätzlich die reale JSONB-Textform, die der
Asyncpg-Treiber beim Wiedergeben eines Idempotenzbelegs liefert.

## Browsernachweise

Der automatisierte Chromium-Ablauf bedient den vollständigen sensiblen
Workflow mit echten Backenddaten:

1. Statusänderung anfordern und zum Fresh Login wechseln;
2. echten sechsstelligen Code über Worker, SMTP und Mailpit empfangen;
3. Konto sperren und eine vorhandene Browsersitzung sofort abweisen;
4. Konto reaktivieren und die alte Sitzung weiterhin abweisen;
5. einen vollständig neuen Login durchführen;
6. Axe ohne kritische oder ernste Befunde ausführen.

Die privaten Screenshots des gesperrten und reaktivierten Zustands werden mit
Dateimodus `0600` unter `.local/pilot/evidence/identity/` abgelegt und nicht
versioniert.

Der Workflow wurde zusätzlich sichtbar im In-App-Browser der kanonischen
Entwicklungsinstanz bedient. Dabei wurden Bestätigungsdialog, Fresh Login,
echte Mailpit-Nachricht, sofortiger Sitzungsentzug, Reaktivierungsdialog und
der Hinweis auf die erforderliche Neuanmeldung geprüft. Das Testkonto wurde
anschließend wieder aktiviert; die entzogene Sitzung blieb beendet.

## Docker-Ressourcen

Der Test verwendet das exakte Compose-Projekt `leonaid-poc040-test`. Nach dem
erfolgreichen Lauf bestätigte die Inventur jeweils null Container, Netze und
Volumes mit diesem Projektlabel.

Das Cleanup aktiviert dasselbe Mailpit-Profil wie der Aufbau. Dadurch werden
auch Profilcontainer, das Mailnetz und das Mailpit-Volume symmetrisch entfernt.
Der kanonische sichtbare Entwicklungsstack `leonaid` bleibt aktiv.

## Formale Taskgrenze

Alle Kriterien von `PILOT-011` sind technisch bewiesen. Der Task bleibt im
Plan formal offen, weil der Pilotvertrag einen abgeschlossenen Task mit
offener Abhängigkeit ablehnt: `PILOT-011` hängt von `PILOT-010` ab, das wegen
seiner noch offenen Vorbedingungen weiterhin formal offen ist. Diese
Abhängigkeit wird nicht durch einen verfrühten Haken umgangen.
