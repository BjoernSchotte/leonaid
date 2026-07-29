# PILOT-051 – Technischer Onboarding- und Support-Teilnachweis

Stand: 2026-07-29
Ergebnis: Die technische Support-Code-Strecke ist auf realen, isolierten
Diensten und zusätzlich sichtbar im In-App-Browser bewiesen. Ein
ausführbares Onboarding-/Offboarding-Runbook und eine datensparsame
Feedbackvorlage liegen vor. Reale Pilotnutzer, ein unabhängiger Operator,
moderierte Sessions, ein echter Screenreader-Smoke und die formale
P0/P1-Entscheidung bleiben ausdrücklich offen.

## Implementierter Vertrag

- Normale API-Fehler nennen einen Support-Code in verständlicher
  Fehlermeldung.
- Der neue System-Admin-Bereich `Anfrage sicher nachvollziehen` zeigt nur
  Ausgang, Auswirkung, Zeitpunkt, normalisierte Route, HTTP-Status,
  Fehlercode, Release und nächsten Schritt.
- Ein schreibfreier Diagnose-Test erzeugt kontrolliert
  `support_probe_failed` mit HTTP 503.
- Die serverseitige Diagnose ist durch die System-Admin-Rolle geschützt.
- Ein begrenzter, prozesslokaler Ringpuffer hält höchstens 2.000 technische
  Einträge. Er speichert keine Query-Parameter, Header, Identitäten,
  Request-/Response-Payloads oder fachlichen Daten.
- [`../../../infra/pilot/ONBOARDING-SUPPORT-RUNBOOK.md`](../../../infra/pilot/ONBOARDING-SUPPORT-RUNBOOK.md)
  führt Einladen, Rollenwechsel, Sperre, Sessionentzug, Offboarding,
  Support und Eskalation ohne Datenbankwissen aus.
- [`../../../infra/pilot/FEEDBACK-TEMPLATE.md`](../../../infra/pilot/FEEDBACK-TEMPLATE.md)
  bindet Beobachtung, Priorität, Owner und Release an eine private,
  datensparsame Evidence.

## Automatisierter Nachweis ohne Mocks

Ausgeführt:

```text
./leonaid test-unit
./leonaid test-operations
/bin/sh tools/ci/lint-types.sh
```

Ergebnis:

```text
196 passed
operations-test: OK: korrelierte Logs, gezielte Dependency-Ausfälle,
                  sicherer UI-Retry und loghygienische Browser-UX bewiesen
ruff, format, mypy, OpenAPI, frontend-boundary, handoff, TypeScript/Astro
und Prettier: grün
```

`test-operations` startete aus leerem Zustand echtes PostgreSQL, Twenty,
RustFS, Mailpit, Worker, API und Web. Der Test erzeugte den kontrollierten
503, korrelierte den exakten Support-Code über das geschützte Backend und
prüfte, dass weder Payload noch E-Mail, Cookie oder Sponsorinhalt
zurückgegeben werden. Ein anonymer Zugriff wurde abgewiesen. Der
Playwright-Test bediente denselben Ablauf im System-Admin-Portal, prüfte die
mobile Darstellung und Axe gegen die reale Oberfläche.

Der Lauf bewies außerdem echte Twenty-, RustFS-, Mail- und Worker-Ausfälle
sowie Dead-Letter-Recovery. Danach waren keine Container, Netzwerke oder
Volumes des isolierten Projekts mehr vorhanden.

## Sichtbarer In-App-Browser-Nachweis

Am selben Stand wurde im sichtbaren In-App-Browser:

1. ein individueller System-Admin per Login-Code angemeldet;
2. unter `System & Betrieb` der kontrollierte Fehler ausgelöst;
3. der ausgegebene Support-Code in das Diagnosefeld übernommen;
4. der technische Befund bis
   `POST /api/v1/admin/support/probe`,
   `HTTP 503 · support_probe_failed` und Release aufgelöst;
5. das Ergebnis auf das Fehlen von E-Mail, Payload, Cookie und
   Sponsorinhalt geprüft;
6. die Strecke bei 200 % Browserzoom sichtbar bedient.

Eingabe, Aktion, Auswirkung und nächster Schritt blieben bei 200 % Zoom
vollständig erreichbar. Die Browserkonsole enthielt keine Warnungen oder
Fehler. Der kontrollierte 503 erschien ausschließlich als erwarteter
Fachbefund.

## Bewusst offene Gates

Dieser Nachweis schließt `PILOT-051` nicht. Noch erforderlich sind:

- bestätigter Pilotkreis, Zeitraum, Datenschutzinformation und Supportweg;
- individuelle reale Accounts;
- eigenständiges Onboarding und Offboarding durch Charity-/System-Admin;
- moderierte Kernaufgaben mit mindestens einer realen Person je interner
  Persona;
- unabhängiger Operatorlauf nur anhand des Runbooks;
- VoiceOver- oder gleichwertiger echter Screenreader-Smoke;
- reale, datensparsame Feedbackerfassung und Releasezuordnung;
- geschlossene P0/P1-Befunde sowie Entscheidung für offene P2.
