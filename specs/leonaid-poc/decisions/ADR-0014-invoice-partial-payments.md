# ADR-0014: Teil- und Überzahlungen als Zahlungseinträge

- Status: angenommen; ersetzt den Zahlungsteil von ADR-0009
- Datum: 2026-11-06
- Entscheider: Produktverantwortlicher (Freigabe der Funktion) und
  Implementierung
- Referenz: [ADR-0009](ADR-0009-exact-invoice-settlement.md)

## Kontext

ADR-0009 ließ im PoC nur die exakte Vollzahlung zu. Im Pilotbetrieb zahlen
Sponsoren in Raten, runden ab oder überweisen doppelt. Ohne Teilzahlungen
bleibt eine solche Rechnung dauerhaft offen oder wird falsch als bezahlt
markiert. Der Produktverantwortliche hat die Funktion freigegeben.

Weiterhin ausgeschlossen bleiben Bankabgleich, automatische Zuordnung,
Mahnwesen, Payment Provider und eine Erstattungsbuchung.

## Entscheidung

### Mehrere Zahlungseinträge je Rechnung

Ein Zahlungseintrag enthält Betrag (> 0, in Cent, Rechnungswährung),
Eingangsdatum, Verwendungszweck, optionale Notiz, erfassende Person und
Zeitpunkt. Eine Zahlungsart gibt es im Modell nicht. Die Datumsregeln aus
ADR-0009 bleiben: nicht vor dem Rechnungsdatum, nicht in der Zukunft. Für
stornierte Rechnungen wird keine Zahlung erfasst.

### Status aus der Summe

Der Zahlungsstatus folgt aus der Summe der aktiven Einträge:

| Summe            | `settlementStatus` | gespeicherter Rechnungsstatus |
| ---------------- | ------------------ | ----------------------------- |
| 0                | `open`             | `issued` oder `sent`          |
| 0 < Summe < Brutto | `partially_paid` | `issued` oder `sent`          |
| = Brutto         | `paid`             | `paid`                        |
| > Brutto         | `overpaid`         | `paid`                        |

`openMinor` ist immer der Restbetrag (`max(Brutto − Summe, 0)`), stornierte
Rechnungen haben keinen offenen Betrag. Überzahlungen zeigen den
Differenzbetrag und den Hinweis „Differenz erstatten“; die Erstattung selbst
wird außerhalb von LeonAid ausgeführt und nicht gebucht.

Die bestehenden API-Werte von `invoice.status` bleiben unverändert. Der
Teilstatus kommt additiv als `settlementStatus` mit `paidMinor`,
`overpaidMinor`, `payments` und `settlementVersion` hinzu. Ein neuer Wert
in `invoice.status` wäre nach `tools/openapi/breaking.py` ein Breaking
Change gewesen.

### Rückbuchung statt Löschen

Ein Eintrag wird nicht gelöscht, sondern mit einer eigenen
`payment_reversal`-Zeile und Begründung (8–500 Zeichen) zurückgebucht. Er
bleibt sichtbar und zählt nicht mehr zur Summe; der Status wird neu
berechnet. Fällt eine bezahlte Rechnung unter den Bruttobetrag, kehrt sie zu
`sent` zurück, wenn ein Versand bestätigt ist, sonst zu `issued`.

### Berechtigung, Nebenläufigkeit, Nachvollziehbarkeit

Berechtigt sind dieselben Rollen wie in ADR-0009. Erfassung und Rückbuchung
laufen serialisiert je Rechnung mit Idempotency-Key. Beide akzeptieren
`expectedSettlementVersion`; die Version ist die Zahl der Einträge plus
Rückbuchungen und wächst mit jeder Änderung. Eine veraltete Version wird mit
409 `invoice_settlement_stale` abgewiesen. Jeder erfolgreiche Vorgang
erzeugt genau ein AuditEvent (`invoice_payment_recorded`,
`invoice_payment_reversed`) mit Summe, Rest und Überzahlung.

## Konsequenzen

- Bestehende Zahlungen bleiben je ein Eintrag; die Migration entfernt nur die
  Eindeutigkeit „eine Zahlung je Rechnung“.
- Dashboard, Rechnungsliste und Summen rechnen offene und überfällige Beträge
  mit dem Restbetrag.
- Ältere Clients sehen weiterhin `payment` (den neuesten aktiven Eintrag)
  und `openMinor`.
- Die Storno-Regeln aus ADR-0009 bleiben unverändert.
