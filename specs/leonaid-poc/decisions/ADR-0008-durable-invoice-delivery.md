# ADR-0008: Dauerhafter Rechnungsversand über Outbox und SMTP

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 7.2, 8.4 und 12.2

## Kontext

Eine freigegebene Rechnung wird serverseitig mit Typst als PDF erzeugt und
als konkrete, unveränderliche Objektversion in RustFS gespeichert. Der
anschließende E-Mail-Versand darf weder ein neues Dokument erzeugen noch
PDF-Bytes aus einem veränderlichen UI-Zustand ableiten.

SMTP kann nach Annahme einer Nachricht abbrechen, ohne dass der aufrufende
Prozess den Erfolg noch sicher beobachtet. Ein blindes Retry könnte deshalb
dieselbe Rechnung doppelt versenden. Gleichzeitig muss ein tatsächlicher
Ausfall administrativ sichtbar und wiederanlaufbar sein.

## Entscheidung

### Versandauftrag und Zustellung sind getrennt

Der autorisierte FastAPI-Endpunkt legt innerhalb derselben
PostgreSQL-Transaktion einen `InvoiceDelivery`-Snapshot und ein
`invoice.mail.send.requested.v1`-Outbox-Ereignis an. Der Snapshot enthält
Empfänger, Betreff und Klartext der konkreten Zustellung. Ein
Idempotency-Key verhindert doppelte Aufträge bei wiederholten HTTP-Requests.

Der Worker lädt anschließend exakt die im Auftrag referenzierte
RustFS-Objektversion. Vor dem SMTP-Aufruf prüft er Medientyp, Dateigröße und
SHA-256 gegen die serverseitig gespeicherten Dokumentmetadaten. Die
E-Mail-Anlage wird weder neu gerendert noch aus Browserdaten aufgebaut.

### Bestätigte Zustellung ist die Retry-Grenze

Nach erfolgreicher SMTP-Annahme schreibt der Worker eine unveränderliche
`MailDelivery` mit deterministischer Message-ID und markiert das
Outbox-Ereignis als abgeschlossen. Die Message-ID ist je Versandauftrag
stabil.

Existiert bereits eine bestätigte `MailDelivery`, führt ein erneuter
Worker-Lauf keinen weiteren SMTP-Aufruf aus. Ein fehlgeschlagener
Outbox-Auftrag darf nur nach Dead-Letter-Zustand administrativ wieder
eingeplant werden. Ein bestätigter Erfolg ist für Retry gesperrt.

Diese Grenze liefert im PoC eine belastbare
„nicht erneut nach bestätigtem Erfolg“-Semantik. Ein SMTP-Fehler genau nach
externer Annahme und vor lokaler Bestätigung bleibt das bekannte
At-least-once-Fenster. Eine spätere produktive Mail-Provider-Integration
soll deshalb providerseitige Idempotenz oder eine Zustellstatus-API nutzen.

### Bewusster Neuversand ist ein neuer Auftrag

Ein Charity-Admin kann eine bereits bestätigte Rechnung bewusst erneut
versenden. Die Oberfläche verlangt dafür eine zweite Bestätigung. Der
Neuversand erzeugt einen neuen `InvoiceDelivery`- und Outbox-Datensatz mit
eigener Message-ID, verweist aber auf dieselbe `GeneratedDocument`-ID und
dieselbe RustFS-Objektversion.

### Sichtbares Versandprotokoll

Das Rechnungsjournal projiziert den Outbox- und Mail-Delivery-Zustand in
verständliche Fachstatus:

- eingeplant beziehungsweise wird versendet;
- erneuter Versuch;
- fehlgeschlagen mit Versuchszahl und Fehler;
- erfolgreich versendet mit Zeitpunkt und Message-ID.

Charity-Admins dürfen Versand und administrativen Retry auslösen.
Finanz-Leser dürfen Dokument und Protokoll lesen, aber keinen Versand
anstoßen.

## Konsequenzen

- Typst-Erzeugung, RustFS-Ablage und SMTP-Versand bleiben entkoppelte
  serverseitige Schritte.
- Fachlogik und Integritätsprüfung liegen im FastAPI-Core und Worker, nicht
  in Astro-Actions oder Browsercode.
- Ein bewusster Neuversand ist vollständig nachvollziehbar, ohne die
  unveränderliche Rechnung oder ihr PDF zu duplizieren.
- Spätere SMTP- oder API-Mailprovider können hinter dem Versandadapter
  ergänzt werden; Outbox, Zustellprotokoll und UI-Vertrag bleiben bestehen.
- Bounce-, Öffnungs- und Langzeit-Zustellstatus sind nicht Teil von
  POC-094.
