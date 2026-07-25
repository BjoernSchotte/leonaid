# ADR-0002: Beweis- und Auslieferungsprotokoll

- Status: angenommen
- Datum: 2026-07-25
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: `specs/leonaid-poc/PLAN.md`, Kapitel 1.1 und 3

## Kontext

Der PoC integriert mehrere zustandsbehaftete Systeme. Mocks oder isolierte
Happy Paths würden weder Berechtigungen noch Datenintegrität, Zustellung oder
Recovery belegen.

## Entscheidung

Ein Task wird nur dann abgeschlossen, wenn alle Akzeptanzkriterien und
geforderten Unit-, Integrations-, Contract-, E2E- oder Recovery-Nachweise mit
Golden Data erbracht sind.

Der PoC wird ausschließlich Docker-basiert entwickelt und geprüft. Externe
Systeme laufen als reale, exakt gepinnte Container. Fehler werden durch reale
Zustände wie gestoppte Container, entzogene Rechte oder konkurrierende
Requests erzeugt.

Nach jedem vollständig bewiesenen Task werden ausschließlich dessen
Änderungen committed und direkt nach `main` gepusht. Teilfertige Tasks werden
weder abgehakt noch als abgeschlossen veröffentlicht.

## Konsequenzen

- Test- und Produktionscode benutzen dieselben I/O-Adapter.
- Beweisartefakte müssen den fachlichen Zustand, nicht nur einen Statuscode,
  zeigen.
- Testlogins liegen in einer nicht committed lokalen Datei und werden durch
  `.gitignore` geschützt.
- Ein grüner Test ohne passende Abdeckung ist kein Abschlussbeleg.
