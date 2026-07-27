# PoC-Entscheidungsregister

Stand: 2026-07-25

Dieses Register verhindert, dass offene fachliche oder rechtliche Fragen
stillschweigend durch technische Annahmen entschieden werden. Ein offener
Eintrag blockiert erst den genannten Task, nicht automatisch frühere,
unabhängige Implementierung.

## Angenommene Entscheidungen

| ID | Entscheidung | Owner | Datum | Nachweis |
|---|---|---|---|---|
| ARC-001 | Krapfentaxi ist der alleinige PoC-Use-Case | Produktverantwortlicher | 2026-07-25 | ADR-0001 |
| ARC-002 | Tasks werden nur nach realem Golden-Data-Nachweis committed und gepusht | Produktverantwortlicher / Implementierung | 2026-07-25 | ADR-0002 |
| ARC-003 | Der gesamte PoC läuft Docker-basiert | Produktverantwortlicher / Implementierung | 2026-07-25 | ADR-0002, ADR-0003 |
| ARC-004 | Core ist Python/FastAPI; Fachlogik bleibt adapterunabhängig | Produktverantwortlicher / Implementierung | 2026-07-25 | ADR-0003 |
| ARC-005 | RustFS ist PoC-Default hinter einem S3-Port | Produktverantwortlicher / Implementierung | 2026-07-25 | Produktkonzept 7.2 |
| LEG-001 | Rechnungsaussteller kommt aus einem je Aktion explizit bestätigten Profil; das Golden-Profil ist synthetisch | Produktverantwortlicher / Implementierung | 2026-07-27 | ADR-0004 |
| LEG-002 | Steuerfall und Rechtstext sind explizit; Golden nutzt ausschließlich den synthetischen Kleinunternehmerfall | Produktverantwortlicher / Implementierung | 2026-07-27 | ADR-0004 |
| LEG-003 | Nummern werden transaktional eindeutig vergeben und nie wiederverwendet; Storno/Korrektur überschreibt keinen Beleg | Produktverantwortlicher / Implementierung | 2026-07-27 | ADR-0004 |

## Offene Entscheidungen mit spätestem Klärpunkt

| ID | Offene Entscheidung | Owner | Fällig vor | Status |
|---|---|---|---|---|
| LEG-004 | Aufbewahrungs- und Löschfristen je Fachobjekt | Produktverantwortlicher plus Datenschutz/Recht | POC-111 | offen |
| LEG-005 | Produktive Trägerdaten, Steuerfall und E-Rechnungsbedarf der konkreten Installation | Rechtlicher Träger plus Steuerberatung | Produktivfreigabe | offen; der PoC verwendet nur synthetische Daten |
| OPS-001 | Produktiver SMTP/API-Relay | Betrieb | POC-094 | offen; Mailpit ist nur Testsystem |
| OPS-002 | Zweiter realer S3-kompatibler Contract-Endpunkt | Betrieb | POC-092 | offen |

## Scope-Review

Am 2026-07-25 wurde der Scope durch den Produktverantwortlichen in der
Konzeptiteration bestätigt:

- Krapfentaxi ist der erste und einzige Use Case, den der PoC beweisen muss.
- Lions Open und Weihnachtsmarkt sind nachgelagert.
- `specs/leonaid-poc/PLAN.md` ist der verbindliche Implementierungs- und
  Abnahmeplan.
- Jeder Task wird nur nach vollständigem Beweis abgehakt, committed und
  gepusht.
- Testlogins werden erzeugt, lokal erreichbar gemacht und nicht committed.
- Der PoC wird ausschließlich Docker-basiert betrieben.

Änderungen an diesem Scope benötigen einen neuen Registereintrag und, wenn
architektonisch relevant, eine neue ADR. Historische Entscheidungen werden
nicht rückwirkend überschrieben.
