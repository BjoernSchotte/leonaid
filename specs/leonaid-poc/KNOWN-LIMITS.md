# Bekannte Grenzen des PoC

Stand: 2026-07-27

Diese Liste trennt bewusst verschobenen Scope von Defekten. Die
Krapfentaxi-Golden-Journey ist technisch vollständig bewiesen; die folgenden
Punkte sind keine stillschweigenden Produktzusagen.

## Produkt und Fachlichkeit

- Krapfentaxi ist der einzige implementierte End-to-End-Use-Case. Lions Open
  und Weihnachtsmarkt folgen erst nach der PoC-Abnahme.
- Öffentliche Seiten verwenden versionierte Standardformulare. Es gibt
  keinen CMS-, Form-Builder- oder freien Workflow-Editor.
- ERP-light umfasst Bestellungen, Ausgangsrechnungen, Typst-PDFs, Versand und
  manuelle Vollzahlung. Buchhaltung, E-Rechnung, Mahnwesen, Payment Provider,
  Spendenzahlungen und Spendenbescheinigungen fehlen.
- Tourenplanung, Fahrerdisposition, Offline-Sync, Push-Nachrichten,
  Etikettendruck, Herstellerabrechnung und Materialbestand fehlen.
- Dokumentverwaltung umfasst erzeugte und fachlich zugeordnete Belege. Ein
  allgemeines DMS mit freiem Upload, Versionierung und Volltextsuche fehlt.
- listmonk und Canva sind nicht Teil des Core-PoC.

## Identität und Administration

- Passwortloser Login unterstützt E-Mail-Link und sechsstelligen Code.
  Passkeys, SSO, Social Login und öffentliche Selbstregistrierung fehlen.
- Mitglieder können ihre Login-E-Mail nicht selbst ändern.
- Einladungen und Sitzungsentzug sind implementiert. Für Account-Sperre,
  Membership-Entzug, Rollenwechsel und E-Mail-Korrektur gibt es noch keinen
  vollständigen Admin-Workflow. Diese Vorgänge sind vor einem realen Pilot
  umzusetzen; direkte produktive Datenbankänderungen sind kein akzeptierter
  Ersatz.
- Eine Installation bildet genau einen Club/Träger ab. Mehrere Clubs
  benötigen getrennte Installationen.

## Betrieb und Produktivfreigabe

- Der PoC ist für einen einzelnen Docker-Compose-Host ausgelegt. Es gibt
  keine Hochverfügbarkeit, automatische horizontale Skalierung oder
  unterbrechungsfreie Multi-Region-Wiederherstellung.
- Mailpit ist ausschließlich lokales Testsystem. Der produktive
  SMTP-/API-Relay ist noch auszuwählen und zu konfigurieren.
- Backups, Restore und Upgrade sind technisch bewiesen. Der konkrete
  Off-VPS-Storage, Secret-Manager, DNS-Betrieb und Alarmkanal bleiben
  Betreiberentscheidungen.
- Rechtliche Aufbewahrungs-/Löschfristen, produktive Trägerdaten,
  Steuerfall und E-Rechnungsbedarf benötigen Datenschutz-, Rechts- und
  Steuerfreigabe.
- OpenFeature ist integriert; der PoC bietet zwei administrative Flags.
  Ein externes Flag-Backend, Segmentierung und gestaffelte Prozent-Rollouts
  fehlen.
- RustFS ist der PoC-Default. SeaweedFS beweist nur den neutralen S3-Vertrag
  und ist kein zweiter produktiver Cluster.

## Einordnung

Aktuell sind keine bekannten P0-/P1-Defekte in der bewiesenen
Krapfentaxi-Golden-Journey offen. Die genannten Grenzen blockieren je nach
Einsatz eine Produktiv- oder Pilotfreigabe und dürfen nicht durch die
technische PoC-Abnahme übergangen werden. Offene fachliche und rechtliche
Entscheidungen stehen zusätzlich in [`DECISIONS.md`](DECISIONS.md).
