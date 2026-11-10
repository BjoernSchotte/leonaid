# ADR-0015: Nummernkreise der Installation und die Stornorechnung

- Status: angenommen; ersetzt in [ADR-0004](ADR-0004-invoice-issuing.md) den
  Satz „Der Nummernkreis gilt pro Aktion und Präfix“ und schließt den dort
  und in [ADR-0009](ADR-0009-exact-invoice-settlement.md) offen gelassenen
  Nummern- und Verknüpfungsvertrag des Korrekturbelegs
- Datum: 2026-11-10
- Entscheider: Produktverantwortlicher (Auftrag vom 2026-11-10, Entscheidungen
  D-C1 bis D-C4 durch die Leitung, vom Produktverantwortlichen korrigierbar)
  und Implementierung
- Referenz: `specs/mails-documents-donations-push/PLAN.md` §5.2, §5.3, §7

## Kontext

ADR-0004 zählte Rechnungsnummern je Aktion (`invoice_profile.next_number`).
Das Präfix kommt aber aus der Rechtskonfiguration und gilt für die ganze
Installation, und `invoice.number` ist für die ganze Installation eindeutig.
Sobald zwei Aktionen dasselbe Präfix haben, vergibt die zweite Aktion mit
ihrer ersten Rechnung eine Nummer, die die erste Aktion schon vergeben hat.
Die Datenbank weist das ab; die Rechnung lässt sich dann nicht ausstellen.

Außerdem erzeugte kein Anwendungscode ein Rechnungsprofil. Eine neu angelegte
Aktion konnte keine Rechnung ausstellen (`invoice_profile_missing`).

Ein Storno ließ bisher nur den Status `cancelled` zurück. Einen eigenen
Beleg mit Nummer gab es nicht. ADR-0004 und ADR-0009 haben seinen Nummern- und
Verknüpfungsvertrag ausdrücklich offen gelassen.

Mit Spendenzusagen und Zuwendungsbestätigungen kommen zwei weitere
nummerierte Belegarten dazu. Sie brauchen dieselbe Zählung.

## Entscheidung

### Ein Nummernkreis je Belegart und Präfix, für die Installation

`document_series(kind, prefix, next_number, width)` mit dem Schlüssel
`(kind, prefix)` ist der einzige Zähler. Belegarten sind `invoice`,
`donation` und `donation_receipt`.

Eine Nummer wird in der Transaktion ihres Belegs vergeben: Zeile sperren,
lesen, mit Compare-and-Swap weiterzählen. Die Zeile wird nach den Sperren
von Rechnung und Bestellung genommen (Sperrreihenfolge in
`adapters/postgres/retry.py`) und bis zum Ende des Befehls gehalten; alle
Aktionen eines Präfixes teilen sie sich. Eine
gescheiterte Transaktion verbraucht keine Nummer. Eine vergebene Nummer wird
nie wiederverwendet; das gilt aus ADR-0004 weiter.

Ein Nummernkreis entsteht, wenn ein Präfix zum ersten Mal gebraucht wird:
bei der Aktivierung einer Rechtskonfiguration oder bei der ersten Vergabe.
Er beginnt hinter der höchsten Nummer, die irgendein Beleg mit diesem Präfix
schon trägt. Ein Präfix, das später wieder verwendet wird, wiederholt also
keine Nummer. Die Stellenbreite folgt der Rechtskonfiguration. Beginnt ein Präfix mit
einem anderen (`RE` und `RE2026`), gehört eine Nummer zum längsten bekannten
Präfix, mit dem sie anfängt.

Steht der Zähler hinter einer schon vergebenen Nummer (eine Rechnung, die
ein Prozess der Vorversion nach der Migration geschrieben hat, oder ein von
Hand eingespielter Beleg), rückt die Vergabe ihn in derselben Transaktion
auf die nächste Nummer, die noch kein Beleg trägt. Übersprungen werden nur
Nummern, die es gibt; es entsteht weder eine Lücke noch eine doppelte Nummer. Ohne
diese Regel scheiterte jede weitere Freigabe und jedes Storno des Präfixes
dauerhaft.

`invoice_profile.next_number` bleibt eine Version lang in der Tabelle. Die
Anwendung liest und schreibt die Spalte nicht mehr. Die Rückmigration
schreibt den Stand des Nummernkreises in sie zurück.

### Jede Nummer gibt es in der Installation einmal

`document_number(number)` enthält jede vergebene Nummer jeder Belegart. Ein
Datenbank-Trigger an jeder Belegtabelle trägt die Nummer beim Speichern ein.
Zwei Belege aus verschiedenen Tabellen können deshalb keine Nummer teilen,
auch wenn ein Fehler im Anwendungscode es versuchte. Eine Nummer wird einmal
gesetzt und nicht geändert.

Die Präfixe verschiedener Belegarten müssen sich unterscheiden. Die
Rechtskonfiguration prüft das, sobald sie die Präfixe für Spenden aufnimmt.

### Die Stornorechnung nimmt die nächste Nummer des Rechnungsnummernkreises

Wer eine Rechnung storniert, stellt im selben Schritt die Stornorechnung aus
(D-C1). Sie ist ein eigener Beleg:

- eigene Nummer aus dem Nummernkreis `invoice`, mit dem Präfix, das am Tag
  des Stornos gilt: das Präfix des Rechnungsprofils der Aktion; ohne Profil
  das der aktiven Rechtskonfiguration; ohne diese der Nummernkreis, zu dem
  die Nummer der Rechnung selbst gehört. Ein Storno scheitert nie daran, dass
  ein Profil fehlt;
- Datum ist der Tag des Stornos in der Zeitzone des Clubs;
- Aussteller, Empfänger, Steuerfall und Positionen der Rechnung;
- Nummer und Datum der Rechnung, die sie aufhebt.

Eine gemeinsame, lückenlose Reihe aller Ausgangsbelege ist am einfachsten zu
erklären und zu prüfen. Der Beleg nennt die Rechnung, auf die er sich bezieht.

Die Rechnung selbst bleibt unverändert: Status `cancelled`, Nummer, Snapshot
und PDF bleiben (ADR-0009).

Die Stornorechnung liegt an `invoice_cancellation` (`number`, `issued_on`,
`issued_at`, `snapshot`, `document_version`). Diese Felder sind nach dem
Ausstellen unveränderlich. Beide Stornowege stellen sie in ihrer Transaktion
aus: `cancelInvoice` und `cancelCommitment`.

### Beträge bleiben nicht negativ gespeichert

Geldbeträge und Mengen sind in LeonAid überall nicht negativ, im Typ und in
den Datenbankprüfungen. Der Snapshot der Stornorechnung speichert die Beträge
der Rechnung unverändert. Allein der Belegtyp
`InvoiceCancellationDocument` weiß, dass die Stornorechnung sie mit Minus
ausweist. Null bleibt null.

### Nur das vollständige Storno

Es gibt kein Teilstorno und keine Korrekturrechnung, die Positionen ersetzt
(D-C3). Eine Korrektur heißt weiterhin: stornieren, dann neu ausstellen. Zu
einer Bestellung gibt es eine Rechnung (`uq_invoice_commitment`); die neue
Rechnung gehört deshalb zu einer neuen Bestellung.

Zahlungen einer stornierten Rechnung bleiben erfasst und lassen sich nicht
zurückbuchen (ADR-0014). LeonAid bucht keine Erstattung. Hat die Rechnung
Geld erhalten, nennt die Stornorechnung den Betrag und den Satz „Die
Erstattung erfolgt gesondert.“. Die Rechnungsliste zeigt „Erstattung offen“,
bis eine berechtigte Person „Erstattung erledigt“ mit Datum vermerkt. Der
Vermerk verlangt wie eine Rückbuchung eine frische Anmeldung und einen
Idempotency-Key und wird protokolliert. Er lässt sich mit Begründung
zurücknehmen („Erstattung zurücknehmen“); `invoice_refund_withdrawal` hält
fest, wer ihn gesetzt und wer ihn zurückgenommen hat. Das Datum darf vor dem
Storno liegen, aber nicht vor dem Rechnungsdatum.

`cancelCommitment` lehnt weiter ab, solange eine nicht stornierte Rechnung
eine Zahlung trägt. Ist die Rechnung bereits storniert, blockiert ihre Zahlung
die Bestellung nicht mehr: Sie ließe sich nicht mehr zurückbuchen, und die
Bestellung bliebe sonst für immer offen.

### Ältere Stornos erhalten keinen erfundenen Beleg

Die Migration stellt für Stornos aus der Zeit vor dieser Entscheidung keine
Belege aus (D-C4). Eine berechtigte Person kann die Stornorechnung später
ausstellen. Sie bekommt dann die nächste Nummer und das Datum dieses Tages.

### Ein Rechnungsprofil für jede Aktion mit Rechnungsstellung

Ein Profil entsteht aus der aktiven Rechtskonfiguration, wenn eine Aktion die
Fähigkeit `invoicing` bekommt, wenn eine Rechtskonfiguration aktiviert wird,
und einmal durch die Migration. Ohne aktive Rechtskonfiguration gibt es
nichts zu bestätigen: es entsteht kein Profil, und die Freigabe antwortet
wie bisher mit `invoice_profile_missing`.

### Ein Dokumentweg für alle Belegarten

Der Renderauftrag wählt über den Dokumenttyp die Quelle, die Snapshot und
Vorlage ihrer Belegart kennt. Speichern, byteidentisches Zurücklesen und der
Statuswechsel sind für alle gleich. Eine neue Belegart meldet ihre Quelle an.
Neue Aufträge heißen `document.render.requested.v1`; der bisherige Name der
Rechnungsaufträge bleibt gültig.

## Konsequenzen

- Zwei Aktionen mit demselben Präfix zählen in einer Reihe. Die Nummern einer
  Aktion sind dadurch nicht mehr lückenlos für sich, die Reihe des Präfixes
  ist es.
- Stornorechnungen stehen in derselben Reihe wie Rechnungen. Ob sie ein
  eigenes Präfix bekommen sollen, kann der Produktverantwortliche noch anders
  entscheiden (P5 der Spezifikation); das ist dann eine weitere Belegart mit
  eigenem Nummernkreis und ändert nichts an diesem Modell.
- Wird die Stornorechnung mit dem Storno versendet, wartet der Mailauftrag
  auf das PDF, ohne Versuche zu verbrauchen (`OutboxDeferred`), und scheitert
  sichtbar, wenn der Renderauftrag endgültig gescheitert ist.
- `GeneratedDocumentResponse.documentType` kennt den neuen Wert
  `invoice_cancellation_pdf`. Der OpenAPI-Prüfer wertet das als Breaking
  Change; die Freigabe steht in
  `specs/leonaid-poc/openapi-breaking-approvals.json`.
- Der Wortlaut der Stornorechnung ist ein Vorschlag (P2 der Spezifikation,
  Anhang A.2) und steht im Rechts-Runbook als „LEGAL REVIEW PENDING“.
