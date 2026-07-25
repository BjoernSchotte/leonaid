# ADR-0001: Krapfentaxi ist der alleinige PoC-Use-Case

- Status: angenommen
- Datum: 2026-07-25
- Entscheider: Produktverantwortlicher
- Referenz: Produkt- und Architekturvorschlag, Kapitel 10

## Kontext

LeonAid soll später unterschiedliche Charity-Aktionen tragen. Der erste
technische Beweis braucht dennoch einen einzigen vollständigen, realen
Vertikalschnitt. Vorauseilende Modellierung von Lions Open oder
Weihnachtsmarkt würde Anforderungen erfinden und den PoC verzögern.

## Entscheidung

Der PoC wird ausschließlich durch Krapfentaxi bewiesen. Enthalten sind der
Action-Core und die Capabilities `acquisition`, `offerings`, `ordering` und
`invoicing` einschließlich Public Web, PWA, Admin-Arbeitsplatz, Rechnung,
Dokumentablage und Versand.

Lions Open und Weihnachtsmarkt beginnen erst nach erfolgreicher
Krapfentaxi-Abnahme mit eigener Discovery, Golden Data und eigenem Plan.

## Konsequenzen

- Das Golden Dataset enthält nur Krapfentaxi-Aktionen.
- Es werden keine Golf-, Turnier-, Stand-, Schicht- oder Marktprozesse gebaut.
- Gemeinsame Core-Begriffe bleiben klein; Krapfentaxi-Daten liegen in
  typisierten Capability-Modulen.
- Die Krapfentaxi-Golden-Journey ist der verbindliche Produktbeweis.
