# LeonAid PoC – Abnahmeprotokoll

Stand: 2026-07-27

## Abnahmekandidat

| Nachweis | Referenz |
| --- | --- |
| bewiesene Code- und Journey-Basis | Commit `ace42c1fc39857f1e6cb64b404d98bd8d93c3c5e` |
| Implementierungsplan | [`PLAN.md`](PLAN.md) |
| externe System- und Image-Locks | [`infra/locks`](../../infra/locks/README.md) |
| Python- und Frontend-Locks | [`uv.lock`](../../uv.lock), [`bun.lock`](../../bun.lock) |
| Golden Dataset | [`tests/fixtures/golden/v1`](../../tests/fixtures/golden/v1/README.md), Version 1.0.0 |
| Testberichte und vollständige Golden Journey | [`POC-122 – Reproduzierbarer Realnachweis`](proofs/POC-122.md#reproduzierbarer-realnachweis) |
| Screenshots und Browser-PDFs | [`POC-122 – Artefakt- und Summennachweis`](proofs/POC-122.md#artefakt--und-summennachweis) |
| UX-/Accessibility-Abnahme | [`POC-102`](proofs/POC-102.md) |
| Security und Datenschutz | [`POC-110`](proofs/POC-110.md), [`POC-111`](proofs/POC-111.md) |
| Backup, Upgrade und Betrieb | [`POC-112`](proofs/POC-112.md), [`POC-113`](proofs/POC-113.md), [`POC-114`](proofs/POC-114.md) |
| Architektur und Entscheidungen | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`DECISIONS.md`](DECISIONS.md) |
| Runbooks | [`RUNBOOKS.md`](RUNBOOKS.md) |
| bewusste Grenzen | [`KNOWN-LIMITS.md`](KNOWN-LIMITS.md) |

## Technischer Status

- [x] Vollständige Krapfentaxi-Journey in Chromium, Firefox und WebKit.
- [x] Zweite Fachrunde ohne technische Duplikate.
- [x] Deterministische Wiederholung aus leeren Golden-Volumes.
- [x] Reale Twenty-, PostgreSQL-, RustFS-, Typst-, Mail- und
      Browserartefakte.
- [x] Sämtliche harten PoC-Gates besitzen einen Nachweis.
- [x] Keine bekannten P0-/P1-Defekte im bewiesenen PoC-Scope.
- [ ] Dokumentierter Fresh-Checkout-Lauf durch eine unbeteiligte technische
      Person protokolliert.
- [ ] Finaler GitHub-Actions-Lauf mit `cold_run=true` grün und hier verlinkt.

Nicht versionierte lokale Beweise liegen nach dem Lauf unter
`.artifacts/poc122/`: JSON-Berichte, Admin-/Akquisiteur-Screenshots,
In-App-Browser-Screenshots und heruntergeladene Typst-PDFs. GitHub Actions
veröffentlicht dieselben Arten von Artefakten mit 14 Tagen Aufbewahrung.

## Fachliche Abnahme

Der Produktverantwortliche führt mindestens diesen Weg aus:

1. Mitglied als Akquisiteur in „Krapfentaxi 2026“ einladen.
2. Einladung per Link oder Code annehmen.
3. neue Firma prüfen, anlegen und automatisch zuordnen.
4. zwei Boxen intern als prüfbereit erfassen.
5. eine Box über `/krapfentaxi` öffentlich bestellen.
6. Feed-Eintrag beim zugeordneten Akquisiteur prüfen.
7. Fresh Login durchführen, Rechnung freigeben und Typst-PDF öffnen.
8. Rechnung versenden, Vollzahlung erfassen und Dashboard prüfen.
9. [`KNOWN-LIMITS.md`](KNOWN-LIMITS.md) als akzeptierte PoC-Grenze lesen.

- [ ] Produktverantwortlicher nimmt diesen PoC-Schnitt ausdrücklich ab.

Die technische Fertigstellung ersetzt weder Produktivfreigabe noch Rechts-,
Datenschutz-, Steuer- oder Betreiberfreigabe.
