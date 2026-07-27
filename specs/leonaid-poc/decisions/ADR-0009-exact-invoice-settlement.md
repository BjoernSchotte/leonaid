# ADR-0009: Exakte Vollzahlung und begründetes Rechnungsstorno

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 7.1 und 7.3

## Kontext

Der LeonAid-PoC benötigt ein verständliches Finanzjournal, ist aber keine
vollständige Buchhaltung. Eine berechtigte Person soll einen beobachteten
Bankumsatz manuell einer Rechnung zuordnen und einen fachlich ungültig
gewordenen Beleg stornieren können.

Teilzahlungen, Überzahlungen, Rückerstattungen und Bankabgleich würden
zusätzliche Salden-, Ausgleichs- und Korrekturregeln erfordern. Gleichzeitig
dürfen Zahlung oder Storno weder die bei Freigabe gespeicherten
Rechnungsdaten noch das bereits erzeugte Typst-PDF verändern.

## Entscheidung

### Im PoC wird nur die exakte Vollzahlung verbucht

Ein Zahlungseingang enthält Betrag, Währung, tatsächliches Eingangsdatum,
Zahlungsreferenz, erfassende Person und Erfassungszeit. Betrag und Währung
müssen exakt dem vollständigen Rechnungsbetrag entsprechen. Das Eingangsdatum
darf weder vor der Rechnungsfreigabe noch in der Zukunft liegen.

Teil- und Überzahlungen werden bereits im Fachkern abgewiesen. Die UI erklärt
diese Grenze und aktiviert die Buchung nur für den exakten Betrag. Eine
Zahlung setzt den offenen Betrag auf null und den Belegstatus auf `paid`.

### Storno ist ein eigener, dauerhafter Vorgang

Ein Storno verlangt eine nachvollziehbare Begründung und eine explizite
Bestätigung. Es speichert den vorherigen Rechnungsstatus, die anfordernde
Person und den Zeitpunkt in einem eigenen `InvoiceCancellation`.

Der Belegstatus wechselt auf `cancelled`; Nummer, Empfänger-, Positions- und
Steuersnapshot, Dokumentversion sowie die konkrete RustFS-Objektversion
bleiben unverändert. Eine Korrektur wird als neuer, separat nummerierter
Vorgang modelliert, nicht durch Überschreiben oder Wiederöffnen des
historischen Belegs.

### Berechtigungen und Nachvollziehbarkeit

Charity-Admins dürfen Zahlungen und Stornos ausschließlich für selbst
verwaltete Aktionen erfassen. Eine später explizit vergebene globale
`finance_manager`-Rolle darf diese Finanzaktionen systemweit ausführen.
`finance_reader`, Akquisiteure und Charity-Admins fremder Aktionen bleiben
schreibgeschützt.

Zahlung und Storno laufen transaktional mit Idempotency-Key. Jeder erfolgreiche
Vorgang erzeugt genau ein AuditEvent. Ausgeblendete UI-Aktionen ersetzen die
serverseitige Autorisierung nicht.

## Konsequenzen

- Das Rechnungsjournal kann offene, vollständig bezahlte und stornierte
  Belege samt Herkunft verständlich darstellen.
- Finanzstatus und historisches Rechnungsdokument bleiben getrennte
  Fachobjekte.
- Der PoC vermeidet implizite Saldenlogik und kann trotzdem den realen
  manuellen Abschluss einer Rechnung beweisen.
- Teilzahlungen, Überzahlungen, Rückerstattungen, Bankimport und Mahnwesen
  bleiben ein nachgelagerter gemeinsamer Ausbau.
- Die spätere Korrekturrechnung benötigt einen eigenen Nummern- und
  Verknüpfungsvertrag; sie ist nicht Teil von POC-095.
