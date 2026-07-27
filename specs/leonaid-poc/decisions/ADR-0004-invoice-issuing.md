# ADR-0004: Rechnungsprofil, Freigabe und unveränderliche Belegdaten

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Fachliche Freigabe für einen Produktivbetrieb: rechtlicher Träger und
  Steuerberatung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 7 und 12.2

## Kontext

LeonAid soll aus einer prüfbereiten Bestellung genau eine Ausgangsrechnung
erzeugen. Dabei dürfen CRM-Änderungen, doppelte Freigaben oder spätere
Korrekturen weder Rechnungsnummer noch Empfänger, Positionen, Beträge oder
Rechtstexte einer ausgestellten Rechnung verändern.

Der konkrete rechtliche Träger und Steuerfall unterscheiden sich je
Installation. Sie dürfen deshalb weder aus Twenty abgeleitet noch durch einen
technischen Standardwert vorentschieden werden.

Nach [§ 14 UStG](https://www.gesetze-im-internet.de/ustg_1980/__14.html)
gehören bei einer regulären Rechnung unter anderem Rechnungsaussteller und
-empfänger, Steuernummer oder Umsatzsteuer-ID, Ausstellungsdatum, eindeutige
fortlaufende Rechnungsnummer, Leistungsbeschreibung und -zeitpunkt sowie
Entgelt und Steuerfall zu den Pflichtangaben.

Für Umsätze eines Kleinunternehmers nennt
[§ 34a UStDV](https://www.gesetze-im-internet.de/ustdv_1980/__34a.html)
einen eigenen Mindestumfang und erlaubt ausdrücklich eine sonstige Rechnung.
Ein reines PDF ist seit 2025 keine strukturierte E-Rechnung. Das BMF weist
darauf hin, dass Vereine je nach unternehmerischem Bereich betroffen sein
können und für inländische B2B-Umsätze Übergangs- und Ausnahmeregeln gelten
([BMF-FAQ, Stand März 2026](https://www.bundesfinanzministerium.de/Content/DE/FAQ/e-rechnung.html)).

## Entscheidung

### Bestätigtes Rechnungsprofil

Jede rechnungsfähige Charity-Aktion besitzt ein eigenes, vor Freigabe
fachlich bestätigtes `InvoiceProfile`. Es enthält:

- vollständigen Namen und Anschrift des rechtlichen Trägers;
- Steueridentifikator und Kontaktadresse;
- expliziten Steuerfall, Steuersatz und Steuerhinweis;
- Präfix, nächste Nummer und Stellenbreite des Nummernkreises;
- Zahlungsziel und Bestätigungszeitpunkt.

Ohne Bestätigungszeitpunkt ist keine Rechnungsfreigabe möglich. Produktive
Werte müssen der verantwortliche Träger und die Steuerberatung bestätigen.
Twenty bleibt Kontakt-CRM und ist keine Quelle für rechtliche
Rechnungsausstellerdaten.

Das Golden Dataset verwendet ausschließlich synthetische Daten und den
Steuerfall `small_business` mit null Umsatzsteuer und Hinweis auf § 19 UStG.
Das ist ein PoC-Testfall, keine steuerliche Aussage über einen realen
Lions-Club. `standard_vat` und `tax_exempt` sind strukturell vorgesehen,
dürfen produktiv aber erst nach dokumentierter fachlicher Bestätigung
aktiviert werden.

### Freigabe und Nummernkreis

Eine Rechnung entsteht unmittelbar im Status `issued`, wenn:

1. das Commitment `review_ready` ist und einen vollständigen
   Rechnungsempfänger besitzt;
2. die Aktion Rechnungsstellung aktiviert und ein bestätigtes Profil besitzt;
3. die handelnde Person für diese Aktion Charity-Admin ist;
4. die Anmeldung innerhalb des Fresh-Login-Fensters erneut bestätigt wurde.

Nummern werden innerhalb derselben serialisierbaren Datenbanktransaktion wie
Rechnung, Commitment-Status, Idempotenzbeleg und Audit-Eintrag vergeben. Der
Nummernkreis gilt pro Aktion und Präfix. Eine vergebene Nummer wird nie
wiederverwendet. Fehlgeschlagene Transaktionen verbrauchen keine Nummer;
fachliche Lücken durch Storno, Import oder spätere Prozesse bleiben
nachvollziehbar und werden nicht durch Umnummerierung geschlossen.

### Unveränderlicher Snapshot

Bei der Freigabe speichert LeonAid einen vollständigen Snapshot von:

- Rechnungsaussteller und Rechnungsempfänger;
- Leistungs- und Rechnungsdatum, Fälligkeit und Zahlungsreferenz;
- Position, Menge, Einheit, Einzelpreis, Netto, Steuer und Brutto;
- Steuerfall, Steuersatz und Rechtstext;
- freigebender Person und Freigabezeitpunkt.

Ausgestellte Rechnungsdaten sind in Domain und Datenbank unveränderlich.
Spätere Änderungen in Twenty oder am Rechnungsprofil wirken nur auf künftige
Rechnungen.

`sent`, `paid` und `cancelled` sind nachvollziehbare Statusfortschreibungen.
Ein Storno oder eine Korrektur überschreibt keinen Beleg. Der PoC verhindert
das Überschreiben; der separate Korrekturbeleg mit Referenz zum
Ursprungsbeleg wird erst in einem Folgetask umgesetzt.

### PDF und E-Rechnung

POC-090 erzeugt noch kein Dokument. POC-091 rendert den bestätigten Snapshot
deterministisch mit Typst als PDF. Für den synthetischen
Kleinunternehmer-Testfall ist dieses PDF als sonstige Rechnung vorgesehen.

Die strukturierten Rechnungsdaten sind führend und vom Renderer getrennt.
Typst ersetzt kein E-Rechnungsformat. Vor einem produktiven Steuerfall, der
eine E-Rechnung verlangt, müssen XRechnung oder ZUGFeRD samt Validierung als
zusätzlicher versionierter Renderer implementiert und fachlich abgenommen
werden.

## Konsequenzen

- Eine Installation startet nicht mit stillschweigend nutzbaren
  Rechnungsdaten.
- Freigabe, Nummer und Audit sind ein atomarer Vorgang.
- CRM-Daten sind vor der Freigabe editierbar, danach zählt ausschließlich der
  Rechnungssnapshot.
- API, UI, Typst, RustFS und Versand verwenden denselben strukturierten
  Snapshot.
- Aufbewahrung und produktive Löschregeln bleiben Gegenstand von LEG-004 und
  POC-111.
- Der Produktivbetrieb bleibt bis zur Bestätigung von Träger, Steuerfall und
  E-Rechnungsbedarf gesperrt.
