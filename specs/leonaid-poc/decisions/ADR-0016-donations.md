# ADR-0016: Spenden als eigene Fähigkeit mit empfangender Körperschaft

- Status: angenommen
- Datum: 2026-11-10
- Entscheider: Produktverantwortlicher (Auftrag vom 2026-11-10, D-D1) und
  Leitung (Entscheidungen D-D2 bis D-D9, vom Produktverantwortlichen
  korrigierbar) und Implementierung
- Referenz: `specs/mails-documents-donations-push/PLAN.md` §8, Anhang A.3;
  baut auf [ADR-0015](ADR-0015-document-series.md) auf

## Kontext

LeonAid kannte bisher nur Bestellungen mit Rechnung. Eine Rechnung steht für
eine Leistung mit Gegenleistung. Eine Spende hat keine Gegenleistung. Wer
spendet, braucht keine Rechnung, sondern eine Zahlungsbitte und nach dem
Zahlungseingang eine Zuwendungsbestätigung für die Steuererklärung.

Spenden nimmt in vielen Clubs nicht der Verein entgegen, der die Rechnungen
ausstellt, sondern ein steuerbegünstigter Förderverein. Aussteller der
Rechnung und Empfänger der Spende sind dann zwei Rechtsträger mit zwei
Konten.

Diese Entscheidung legt das Modell fest. Die Zuwendungsbestätigung
(Stufe 5) und die Zusatzspende im Bestellformular (Stufe 6) bauen darauf
auf. Die steuerlichen Punkte beruhen auf dem Wissensstand der
Implementierung und sind keine geprüfte Rechtsauskunft; ein Club lässt sie
vor dem Einsatz von seiner Steuerberatung lesen (Spezifikation §13, P3).

## Entscheidung

### Spenden sind eine Fähigkeit der Aktion

`donations` ist ein neuer Wert von `ActionCapability`, ohne Abhängigkeit von
anderen Fähigkeiten (D-D1). Eine Aktion kann Spenden annehmen, ohne
Bestellungen oder Rechnungen zu haben. Die Fähigkeit folgt der bestehenden
Sperre: Sie lässt sich nur im Entwurf und in der Planung ändern (D-D4). Keine Migration
gibt sie einer bestehenden Aktion oder Vorlage.

### Die empfangende Körperschaft steht in der Rechtskonfiguration

Der Teil „Spenden“ der Rechtskonfiguration beschreibt die Körperschaft, die
Spenden erhält und Zuwendungsbestätigungen unterschreibt (D-D5): Name,
Anschrift, Rechtsform, Finanzamt, Steuernummer, Art und Datum des Bescheids,
bei Freistellungsbescheid und Anlage zum Körperschaftsteuerbescheid der
Veranlagungszeitraum, die begünstigten Zwecke, das Spendenkonto, die
unterzeichnende Person, die Art der Unterschrift, die Präfixe und die
Stellenbreite der beiden Nummernkreise und die Textbausteine.

Der Teil gilt für die ganze Installation und durchläuft denselben
Vier-Augen-Ablauf wie der Rest. Er ist freiwillig: Ein Club ohne Spenden
aktiviert seine Rechtskonfiguration ohne ihn.

Die Körperschaft ist als ein JSON-Objekt an der Version gespeichert
(`legal_configuration_version.donations`). Sie wird immer als Ganzes
gelesen, geprüft und in den Beleg kopiert; einzelne Spalten brächten keine
Abfrage, die es heute gibt.

Rechnungen, Spendenzusagen und Zuwendungsbestätigungen brauchen drei
verschiedene Präfixe. Eine Nummer sagt damit, welche Belegart sie ist
(ADR-0015).

### Keine Spende ohne empfangende Körperschaft

Ohne aktive Rechtskonfiguration mit dem Teil „Spenden“ lässt sich keine
Spende erfassen (D-D6). Der Server lehnt ab
(`donation_receiving_body_missing`), die Verwaltung sagt, was fehlt und wo.
Jede Spende hat deshalb vom ersten Moment an eine Nummer und einen Beleg.

Fällt der Teil später wieder weg, bleiben die vorhandenen Spenden
unverändert und lassen sich weiter buchen. Neue entstehen nicht.

### Die Spende und ihre Nummer

`donation` hält: Aktion, Nummer, Spender (Name, Anschrift, optional E-Mail
und CRM-Bezug) als Snapshot, zugesagter Betrag, Quelle (`admin`,
`public_form`, `acquisition`), optional die Bestellung, mit der sie kam,
Status `pledged`, `paid` oder `cancelled`.

Die Nummer kommt aus dem Nummernkreis `donation` mit dem Präfix der
empfangenden Körperschaft, in der Transaktion der Spende. Sie steht wie jede
Belegnummer in `document_number`. Was der Beleg zeigt, ist nach dem
Speichern unveränderlich: Nummer, Spender, Betrag, Aktion und der Snapshot
der Spendenzusage. Die Spende merkt sich außerdem die Version der
Rechtskonfiguration, aus der die Körperschaft stammt.

### Die Spendenzusage ist keine Rechnung

Jede Spende bekommt sofort das PDF „Spendenzusage {Nummer}“ (D-D2,
Dokumenttyp `donation_pledge_pdf`, Vorlage `donation-pledge-v1`). Es nennt
Betrag, Aktion und Zweck, das Konto der empfangenden Körperschaft, die Nummer
als Verwendungszweck und den Textbaustein der Körperschaft: freiwillig,
ohne Gegenleistung, keine Rechnung, die Zuwendungsbestätigung folgt nach
Zahlungseingang.

Der Beleg hat keine Steuerzeilen und nennt nirgends den Rechnungsaussteller.
Er zeigt Name, Anschrift, Finanzamt und Steuernummer der empfangenden
Körperschaft. Der Snapshot wird mit der Spende eingefroren; das PDF entsteht
wie jedes Dokument im Worker und ist bytegenau wiederholbar.

Versendet wird die Spendenzusage per E-Mail mit dem PDF im Anhang, in dieser
Stufe über einen Knopf. Der Versand nutzt den bestehenden Weg der
Rechnungs-E-Mails (`invoice_delivery`, jetzt mit `donation_id` statt
`invoice_id`): gleiche Wiederholung, gleiche Fehleranzeige, gleicher
Zustellnachweis.

### Eine Zahlung je Spende

„Zahlung erfassen“ hält einmal fest, was angekommen ist: Betrag und Tag
(D-D7). Der Betrag darf von der Zusage abweichen, nach oben und nach unten.
Die Spende ist dann `paid` mit dem eingegangenen Betrag; die
Zuwendungsbestätigung bestätigt später diesen Betrag, nicht die Zusage. Der
Tag liegt nicht in der Zukunft. Er darf vor der Zusage liegen: Geld kann
eingehen, bevor die Spende erfasst ist, und die Zuwendungsbestätigung nennt
diesen Tag als Tag der Zuwendung.

Eine zweite Teilzahlung wird als eigene Spende erfasst. Eine Bestätigung für
Teil- oder Sammelzahlungen bräuchte das Sammelformular und eine Regel für den
Jahreswechsel; beides hat die erste Version nicht.

„Zahlung zurücknehmen“ setzt die Spende mit Begründung auf `pledged` zurück,
solange keine gültige Zuwendungsbestätigung den Betrag bestätigt.
`donation_payment_withdrawal` hält fest, was erfasst war, wer es erfasst und
wer es zurückgenommen hat. Die Tabelle wird nur ergänzt.

### Storno nur ohne Zahlung

Nur eine Spende ohne erfasste Zahlung lässt sich stornieren, mit Begründung.
Die Nummer bleibt vergeben, der Beleg bleibt gespeichert. Eine bezahlte
Spende wird nicht storniert; war die Zahlung ein Irrtum, wird zuerst die
Zahlung zurückgenommen. Eine stornierte Spende ist endgültig.

### Rechte

Lesen darf, wer Rechnungen der Aktion lesen darf. Erfassen, Zahlung buchen,
Zahlung zurücknehmen und stornieren dürfen der verantwortliche Charity-Admin
der Aktion und die globale Finanz-Buchungsrolle. Versenden darf wie bei
Rechnungen nur der verantwortliche Charity-Admin. Jeder schreibende Befehl
verlangt eine frische Anmeldung und einen Idempotency-Key und wird ohne
Spenderdaten protokolliert.

Die Navigation zeigt „Spenden“ unter „Arbeit“, wenn die Person die Finanzen
mindestens einer Aktion mit der Fähigkeit liest oder verwaltet.

### Datenschutz

Spende, Spendenzusage und später die Zuwendungsbestätigung sind steuerliche
Nachweise der Körperschaft. Der Datenschutz-Bericht nennt die Spenden einer
Person. Die Löschung lässt sie wie ausgestellte Rechnungen für die
freigegebene Frist unverändert und nennt den Grund.

### Die Zuwendungsbestätigung

Für eine bezahlte Spende stellt eine berechtigte Person die
Zuwendungsbestätigung aus (D-D3). Sie ist immer die Einzelbestätigung für
eine Geldzuwendung und bestätigt den eingegangenen Betrag und den Tag des
Eingangs. Zu einer Spende gibt es höchstens eine gültige Bestätigung; die
Datenbank erzwingt das.

`donation_receipt` hält Nummer, Datum, Snapshot und die Version der
Rechtskonfiguration. Die Nummer kommt aus dem Nummernkreis
`donation_receipt` mit dem Präfix der empfangenden Körperschaft. Der Snapshot
enthält Körperschaft, Spender, Betrag, Tag der Zuwendung und die
Textbausteine, die am Tag des Ausstellens gelten. Das PDF
(`donation_receipt_pdf`, Vorlage `donation-receipt-v1`) folgt dem amtlichen
Muster für Geldzuwendungen an Körperschaften nach § 5 Abs. 1 Nr. 9 KStG:
Betrag in Ziffern und in Buchstaben, Tag der Zuwendung, kein Verzicht auf
Erstattung von Aufwendungen, der Absatz zum Bescheid je nach Art des
Bescheids, die begünstigten Zwecke, Ort, Datum, unterzeichnende Person und
der Haftungshinweis. Der Betrag in Buchstaben reicht von 0 bis 999.999.999
Euro; Cent stehen als „xx/100“.

Die Bestätigung nennt die Körperschaft und den Bescheid, die am Tag des
Ausstellens gelten. Es muss aber dieselbe Körperschaft sein, an die die
Spende ging: Name und Steuernummer der aktiven Körperschaft müssen denen der
Spendenzusage entsprechen. Nennt die Rechtskonfiguration inzwischen einen
anderen Rechtsträger, wird nichts ausgestellt
(`donation_receipt_body_changed`).

Ist der Bescheid zu alt, wird nichts ausgestellt (D-D9): mehr als fünf Jahre
seit dem Datum eines Freistellungsbescheids oder der Anlage zum
Körperschaftsteuerbescheid, mehr als drei Jahre seit einem Bescheid nach
§ 60a AO (§ 63 Abs. 5 AO). Die Ablehnung nennt Bescheid, letzten Tag und den
Teil der Rechtskonfiguration, der erneuert werden muss. Sie verbraucht keine
Nummer.

Unterschrift (D-D8): Mit `by_hand` hat das PDF eine leere Unterschriftszeile
unter dem Namen. Es wird ausgedruckt und unterschrieben und lässt sich nicht
aus LeonAid versenden. Mit `machine` nennt das PDF die unterzeichnende Person
und den Satz, dass es maschinell erstellt und das Verfahren dem Finanzamt
angezeigt ist; es lässt sich per E-Mail senden. Die Bestätigung behält die
Art der Unterschrift ihres Ausstellungstags.

Eine Bestätigung ist unveränderlich. „Für ungültig erklären“ verlangt einen
Grund und die Angabe, was mit dem Original beim Spender geschehen ist: Es
liegt wieder vor, oder das Finanzamt des Spenders ist informiert. Ohne eine
der beiden Angaben gibt es kein Ungültig-Erklären und damit keine neue
Bestätigung. Das PDF bleibt gespeichert. Eine ungültige Bestätigung wird nie
mehr versendet: Das Ungültig-Erklären beendet in derselben Transaktion jeden
ruhenden Versandauftrag ihres PDFs (wartend oder endgültig fehlgeschlagen),
der Neustart eines Versands wird abgelehnt (`donation_receipt_void`), und der
Mail-Worker prüft die Bestätigung unmittelbar vor dem Senden. Er hält sie
dabei gegen eine Änderung fest: Ein Ungültig-Erklären während des Sendens
wartet, bis die E-Mail verbucht ist. Danach kann eine neue Bestätigung
mit der nächsten Nummer ausgestellt werden. Solange eine gültige Bestätigung
besteht, lässt sich die Zahlung der Spende nicht zurücknehmen.

Ausstellen und Ungültig-Erklären dürfen der verantwortliche Charity-Admin
und die globale Finanz-Buchungsrolle, mit frischer Anmeldung und
Idempotency-Key. Versenden darf nur der verantwortliche Charity-Admin.

## Folgen

- Neue Tabellen `donation`, `donation_payment_withdrawal` und
  `donation_receipt`;
  `generated_document` und `invoice_delivery` können zu einer Spende gehören.
- Die Rückmigration lehnt ab, solange es Spenden gibt oder eine Aktion oder
  eine Rechtskonfiguration die neuen Teile nutzt.
- Der Golden-Datensatz hat die synthetische empfangende Körperschaft
  „Förderverein Lions Club Musterstadt e. V.“ und die Fähigkeit an der Aktion
  „Krapfentaxi 2026“. Ein erneuter Seed ersetzt die Rechtskonfiguration und
  löscht deshalb alle Spenden der Installation.
- Die Textbausteine in `legal-templates.ts` sind Vorschläge („LEGAL REVIEW
  PENDING“).

## Nicht entschieden

- Sachspenden, Aufwandsspenden, Sammelbestätigungen und Spenden in anderer
  Währung gibt es nicht.
- Die Zusatzspende im Bestellformular regelt Stufe 6.
