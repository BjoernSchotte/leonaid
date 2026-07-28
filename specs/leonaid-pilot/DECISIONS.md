# Pilot-Entscheidungsregister

Stand: 2026-07-28

Dieses Register ist die öffentliche, maschinenlesbare Sicht auf die
Freigabereife einer konkreten LeonAid-Installation. Es dokumentiert keine
Rechts- oder Steuerberatung und enthält weder Namen noch Verträge,
Steuerunterlagen, Zugangsdaten oder andere private Nachweise. Solche Nachweise
liegen im privaten Evidence Store; hier steht nur ihre stabile Referenz-ID.

`open` bedeutet: Die zuständige Rolle muss die Entscheidung noch treffen.
`accepted` bedeutet: Ergebnis und Nachweis wurden durch die zuständige Rolle
bestätigt. `stop` bedeutet: Der aktuelle Pilot-Scope reicht nicht aus. Eine
erforderliche E-Rechnung oder vollständige Buchhaltung ist immer `stop`.

Die offenen Werte sind Absicht. Sie dürfen nicht durch die Implementierung
erraten oder anhand des synthetischen Golden Dataset übernommen werden.
Die konkreten Fachfragen und sicheren Übergaberegeln stehen im
[`DECISION-INTAKE.md`](DECISION-INTAKE.md).

## Gate-relevante Entscheidungen

| ID | Bereich | Entscheidung | Owner-Rolle | Erfasst am | Quelle | Evidence-ID | Status | Wert | Spätestes Gate |
|---|---|---|---|---|---|---|---|---|---|
| PILOT-LEG-001 | Träger | Rechtlicher Träger und Rechnungsaussteller | Rechtlicher Träger | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-release |
| PILOT-TAX-001 | Steuer | Steuerbehandlung der Krapfentaxi-Leistung | Steuerberatung und rechtlicher Träger | 2026-07-28 | ADR-0002 | PENDING | open | PENDING | pilot-release |
| PILOT-INV-001 | Rechnung | Pflichtangaben und Freigabeverantwortung | Rechtlicher Träger und Steuerberatung | 2026-07-28 | ADR-0002 | PENDING | open | PENDING | pilot-release |
| PILOT-INV-002 | Rechnung | E-Rechnungsbedarf im Pilotzeitraum | Steuerberatung und rechtlicher Träger | 2026-07-28 | ADR-0002 | PENDING | open | PENDING | pilot-release |
| PILOT-PRIV-001 | Datenschutz | Aufbewahrungs-, Sperr- und Löschfristen je Fachobjekt | Datenschutz und rechtlicher Träger | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-import |
| PILOT-PRIV-002 | Datenschutz | Rechtsgrundlagen und Informationstexte | Datenschutz und rechtlicher Träger | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-release |
| PILOT-MAIL-001 | Betrieb | Produktiver Mail-Relay und Mail-Domain-Owner | Betrieb | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-deploy |
| PILOT-OPS-001 | Betrieb | DNS-Owner und produktive Domain | Betrieb | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-deploy |
| PILOT-OPS-002 | Betrieb | VPS-Owner und Hosting-Verantwortung | Betrieb | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-deploy |
| PILOT-OPS-003 | Betrieb | Backup-Owner und Wiederherstellungsziel | Betrieb | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-backup |
| PILOT-OPS-004 | Betrieb | Secret-Owner und Übergabeweg | Betrieb | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-deploy |
| PILOT-OPS-005 | Betrieb | Monitoring-Owner und Alarmweg | Betrieb | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-deploy |
| PILOT-OPS-006 | Betrieb | Incident-Owner und Eskalationsweg | Betrieb | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-deploy |
| PILOT-RUN-001 | Pilot | Pilotzeitraum, maximale Nutzerzahl und Go/No-Go-Rolle | Produktverantwortlicher und Betrieb | 2026-07-28 | ADR-0001 | PENDING | open | PENDING | pilot-deploy |

## Zulässige Ergebnisse

- `PILOT-TAX-001`: `small_business`, `standard_vat`, `tax_exempt` oder
  `full_accounting_required`.
- `PILOT-INV-002`: `not_required` oder `required`.
- Alle übrigen Entscheidungen verwenden nach Freigabe den Wert `confirmed`;
  konkrete private Inhalte bleiben ausschließlich im Evidence Store.
- Evidence-IDs beginnen mit `EVID-` und sind nicht aus Namen, E-Mail-Adressen
  oder anderen personenbezogenen Daten gebildet.

## Verantwortungsgrenze

Die Implementierung stellt Struktur, Validierung, Sichtbarkeit, Versionierung
und Sperren bereit. Rechtlicher Träger, Steuerberatung, Datenschutz, Betrieb
und Produktverantwortung treffen die ihnen zugeordneten Entscheidungen. Die
spätere Admin-Oberfläche bildet dieselben Felder als geführte
Freigabeoberfläche ab; Zugangsdaten und Dokumentbytes werden dort nicht
gespeichert.
