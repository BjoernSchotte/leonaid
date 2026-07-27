# ADR-0005: Versionierter serverseitiger Typst-Rechnungsrenderer

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 6, 7 und 12.2

## Kontext

Der in POC-090 freigegebene Rechnungssnapshot muss als dauerhaft
reproduzierbares PDF ausgegeben werden. Der Renderer darf weder veränderliche
Twenty-Daten nachladen noch fachliche Beträge neu berechnen. Gleiche
Snapshots und dieselbe Render-Version müssen dieselben PDF-Bytes erzeugen.

Der PoC benötigt außerdem eine belastbare Grenze zwischen strukturierten
Rechnungsdaten und PDF-Darstellung. Ein PDF ist kein Ersatz für ein
gegebenenfalls erforderliches strukturiertes E-Rechnungsformat.

## Entscheidung

### Führender Snapshot und Renderer-Port

`InvoiceDocumentSnapshot` enthält ausschließlich unveränderliche Daten einer
ausgestellten Rechnung. Er wird aus dem persistierten `Invoice` erzeugt und
über einen rendererneutralen `InvoicePdfRenderer`-Port übergeben.

Typst erhält ein eigenes Darstellungs-JSON. Datum, Geldbetrag und Einheit
werden serverseitig und locale-stabil formatiert. Status, aktueller
CRM-Datensatz, Berechtigungen oder andere veränderliche Felder gelangen nicht
in die Vorlage.

### Version und Ausführung

Die erste Render-Version lautet `invoice-v1+typst-0.13.1`. Sie verbindet:

- die versionierte Vorlage `invoice-v1.typ`;
- Typst 0.13.1 aus dem per SHA-256 gepinnten Container-Image;
- den unveränderlichen Rechnungssnapshot.

Der Core-Container enthält das statische Typst-Binary. Der Adapter prüft die
Laufzeitversion, schreibt Vorlage und sortiertes kompaktes JSON in ein
temporäres Verzeichnis und ruft `typst compile` mit genau einem Job auf. Der
PDF-Erzeugungszeitpunkt entspricht dem Freigabezeitpunkt. Test und CI führen
den Renderer ohne Netzwerk und mit read-only Root-Dateisystem aus.

Rendererdiagnosen enthalten weder Snapshotdaten noch temporäre Pfade. Ein
unvollständiges oder nicht als PDF erkennbares Ergebnis wird verworfen.

### Vorlage und Ressourcen

Die Vorlage verwendet A4, die LeonAid/Lions-Farbwelt und ausschließlich die
in Typst enthaltene Schrift `Libertinus Serif`. Sie lädt zur Laufzeit keine
Schrift, Grafik, URL oder Typst-Package.

Sie behandelt:

- normale und lange Empfänger- und Ausstellerdaten;
- eine oder viele Rechnungspositionen;
- wiederholte Tabellenüberschriften auf Folgeseiten;
- Summen-, Steuer-, Zahlungs- und Ausstellerblöcke nach einem Seitenumbruch;
- Dokumenttitel, Autor, Render-Version und Freigabezeitpunkt als
  PDF-Metadaten.

Die Render-Version bleibt in den Metadaten, erscheint aber nicht im
kundenlesbaren Footer.

### Verifikation

Der reale Vertrag rendert jede Golden-Rechnung zweimal und vergleicht Bytes
und SHA-256. Ein zusätzlicher Layoutfall enthält eine lange Firma, lange
Anschrift und 28 Positionen und erzeugt drei Seiten.

`pypdf` und MuPDF öffnen jedes PDF unabhängig voneinander und extrahieren
Inhalt und Beträge. MuPDF prüft die eingebetteten Fontdaten und rendert alle
Seiten als PNG. Vier visuell freigegebene Referenzseiten werden bytegenau
verglichen. Die normale Rechnung wird zusätzlich sichtbar im
Chromium-PDF-Viewer geöffnet.

## Konsequenzen

- PDF-Darstellung kann geändert werden, ohne das Rechnungsmodell oder Twenty
  zu koppeln; jede Änderung erfordert eine neue Render- oder Vorlagenversion.
- RustFS, Dokumentzuordnungen und Versand erhalten in POC-092 bis POC-094 die
  bereits erzeugten Bytes und SHA-256; sie rendern nicht erneut.
- Ein einmal versandtes Dokument darf nie durch ein neu gerendertes PDF
  überschrieben werden.
- XRechnung oder ZUGFeRD bleiben zusätzliche Renderer desselben
  strukturierten Snapshots und benötigen eine eigene fachliche Validierung.
- Eine absichtliche Layoutänderung erzeugt zunächst nur Kandidaten.
  Referenzbilder werden erst nach visueller Prüfung versioniert.
