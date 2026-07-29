# PILOT-052 – Technischer Tagesreport-Teilnachweis

Stand: 2026-07-29
Ergebnis: Der technische Vertrag für einen sanitizten Pilot-Tagesreport ist
auf realen, isolierten Diensten bewiesen. Der Report führt Backup, Alerts,
Outbox, Speicher, TLS und alle vier Kernabhängigkeiten zusammen, besitzt
stabile Stop-Gründe und eine serverseitig berechnete SHA-256-Prüfsumme. Ein
tatsächlich durchgeführter Live-Pilot und täglich abgelegte reale Reports
bleiben ausdrücklich offen.

## Implementierter Vertrag

- Nur System-Admins dürfen
  `GET /api/v1/admin/pilot/reports/daily` aufrufen.
- Der Report wird bei jedem Abruf aus dem aktuellen Operations-Snapshot
  erzeugt und nicht aus einem Browsercache rekonstruiert.
- `ready`, `attention` und `blocked` unterscheiden den technischen Zustand.
- Stabile Stop-Gründe identifizieren fehlende beziehungsweise kritische
  Backup-, Speicher- und TLS-Checks, P0/P1-Alerts, Dead Letters, inaktive
  Monitoringbausteine und nicht erreichbare Kernabhängigkeiten.
- Der Response ist `no-store`. Header und Body enthalten dieselbe kanonische
  SHA-256-Prüfsumme.
- Der Download enthält keine Namen, E-Mail-Adressen, Sponsor-, Bestell-,
  Rechnungs-, Zahlungs-, Request- oder Response-Payloads.
- Der System-Admin-Bereich zeigt sechs kompakte Prüffelder, Stop-Gründe,
  nächsten Schritt, Release und Prüfsumme und bietet den JSON-Download an.
- [`../../../infra/pilot/LIVE-PILOT-RUNBOOK.md`](../../../infra/pilot/LIVE-PILOT-RUNBOOK.md)
  grenzt Technikzustand und fachliche Pilotfreigabe ausdrücklich voneinander
  ab.

## Automatisierter Nachweis ohne Mocks

Ausgeführt:

```text
./leonaid test-unit
/bin/sh tools/ci/lint-types.sh
./leonaid test-operations
```

Ergebnis:

```text
198 passed
ruff, format, mypy, OpenAPI, frontend-boundary, handoff, TypeScript/Astro
und Prettier: grün
1 Chromium-E2E-Test: grün
operations-test: OK: korrelierte Logs, gezielte Dependency-Ausfälle,
                  sicherer UI-Retry und loghygienische Browser-UX bewiesen
```

`test-operations` startete aus leerem Zustand echtes PostgreSQL, Twenty,
RustFS, Mailpit, Worker, API und Web. Der Contract-Test prüfte Schema, Scope,
Cacheverbot und eine unabhängig neu berechnete Prüfsumme. Ein anonymer
Zugriff wurde abgewiesen. Gezielte Ausfälle von Twenty, RustFS,
Mail-Provider und Worker erschienen als passende technische Stop-Gründe.

Der Playwright-Test bediente den Tagesreport im realen System-Admin-Portal,
prüfte die sechs Bereiche, den blockierenden lokalen Monitoringstatus,
Stop-Grund und nächsten Schritt und lud die echte JSON-Datei im Browser
herunter. Weder UI noch Download enthielten PII oder fachliche Payloads.
Danach waren keine Container, Netze oder Volumes des isolierten
`leonaid-poc114-test`-Projekts mehr vorhanden.

## Sichtbarer In-App-Browser-Nachweis

Am selben Stand wurde im sichtbaren In-App-Browser:

1. der bereits individuell angemeldete System-Admin unter
   `System & Betrieb` geöffnet;
2. der technische Tagesreport serverseitig neu erzeugt;
3. `4/4 Dienste`, Backup, Alarmierung, Outbox, Speicher, HTTPS, Release,
   Stop-Gründe, nächsten Schritt und gekürzte Prüfsumme geprüft;
4. bestätigt, dass Reportbereich und dargestellte Werte weder E-Mail-Adresse
   noch Sponsor-, Bestell-, Rechnungs-, Zahlungs-, Cookie- oder
   Payloadinhalt enthalten;
5. die JSON-Download-Aktion sichtbar ausgelöst;
6. die vollständige Reportkarte und der Download bei explizit eingestellten
   200 Prozent Browserzoom bedient.

Der Downloadinhalt und seine Prüfsumme sind zusätzlich durch den realen
automatisierten Chromium-Download bewiesen. Die Browserkonsole enthielt im
sichtbaren Lauf keine Warnungen oder Fehler. Der Tab blieb für die
Nachvollziehbarkeit auf dem blockierten lokalen Tagesreport geöffnet.

## Bewusst offene Gates

Dieser Nachweis schließt `PILOT-052` nicht. Noch erforderlich sind:

- festgelegter Go-Live-Zeitpunkt, Pilotdauer, Nutzerzahl, öffentliche URL und
  Abbruchkriterien;
- kontrollierte Aktivierung des Public Forms;
- tatsächlich täglich ausgeführte und privat abgelegte sanitizte Reports;
- fachlich bestätigte reale interne und öffentliche Vorgänge;
- Backup-Restore-Smoke und Alarm-Canary im tatsächlichen Pilotfenster;
- bearbeitete reale Support-/Incidentfälle;
- geschlossene P0/P1-Befunde und angewandte Stopregeln;
- Abschlussreport und bestätigte Behandlung der Pilotdaten.
