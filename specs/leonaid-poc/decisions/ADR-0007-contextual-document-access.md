# ADR-0007: Kontextbezogener Dokumentabruf mit zentraler Finanzberechtigung

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 6, 7.2 und 12.2

## Kontext

Ein Rechnungsdokument gehört fachlich nicht nur zur Rechnung. Charity-Admins
und Finanzrollen müssen es auch ausgehend von Charity-Aktion, Bestellung
sowie der betroffenen Firma oder Kontaktperson wiederfinden können.
Gleichzeitig darf eine Akquise-Zuordnung zur Firma keinen Zugriff auf
Finanzdokumente eröffnen.

Die UI benötigt verständliche Metadaten und geschützte PDF-Bytes, aber keine
internen RustFS-Bezüge. Eine fehlende konkrete Objektversion darf nicht als
erfolgreicher leerer Download erscheinen.

## Entscheidung

### Ein Dokument, mehrere explizite Fachreferenzen

`GeneratedDocument` bleibt das zentrale Dokument-Read-Model. Es trägt
explizite Referenzen auf:

- Charity-Aktion;
- Commitment beziehungsweise Bestellung;
- Rechnung;
- Twenty-Firma;
- Twenty-Kontaktperson.

Eigene Leseendpunkte lösen jede Referenz zusammen mit der Action-ID auf. Die
PostgreSQL-Abfrage begrenzt deshalb immer zuerst auf die Charity-Aktion und
erst danach auf die jeweilige Fachreferenz. Zusammengesetzte Indizes aus
Referenz und Erzeugungszeit unterstützen die vorgesehenen Zugriffswege.

### Eine zentrale Finanzberechtigung

Alle Listen- und Downloadpfade verwenden dieselbe serverseitige
Finanz-Leseberechtigung:

- Charity-Admin der Aktion darf lesen;
- Finanzrolle der Aktion beziehungsweise eine spätere globale Finanzrolle
  darf lesen;
- Akquisiteur darf auch bei eigener Firmen- oder Kontaktzuordnung nicht
  lesen.

Die Berechtigung wird vor Repository- und RustFS-Zugriff geprüft. Ein
Dokument aus einer anderen Aktion wird im autorisierten Zielkontext nicht
gefunden und liefert keine Bytes.

### Öffentliche Metadaten, private Speicheridentität

Die autorisierte API liefert Dateiname, Medientyp, Größe, fachliche Version,
Render-Version, Status und Zeitpunkte sowie die Fachreferenzen. Bucket,
Object Key, Storage-Version-ID und SHA-256 bleiben serverintern.

Die Oberfläche zeigt Rechnungs-PDF, Zustand, Dateiname, Typ, Größe, Version
und Erzeugungszeit direkt im aufgeklappten Beleg. Vorschau und Download
verwenden den geschützten Core-Endpunkt und dessen binären OpenAPI-Vertrag.
Die Vorschau kapselt die geladenen Blob-Bytes in einer kontrollierten
Browseransicht; wichtige Fachlogik verbleibt im Core.

### Diagnostizierbarer Speicherfehler

Existiert der PostgreSQL-Eintrag, aber die konkret referenzierte
RustFS-Objektversion nicht mehr, bleibt das Dokument im Fachkontext
auffindbar. Der Download liefert HTTP 503 mit dem stabilen Fehlercode
`generated_document_storage_missing` und einer JSON-Fehlerantwort. Er liefert
weder leere noch vermeintlich erfolgreiche PDF-Bytes.

## Konsequenzen

- Weitere Dokumenttypen können dieselben Fachreferenzen und dieselbe
  zentrale Berechtigungsstrecke verwenden.
- Detailseiten für Bestellung, Firma oder Kontakt können später denselben
  API-Vertrag einbetten, ohne Speicherlogik zu duplizieren.
- Die PoC-Oberfläche zeigt Rechnungsdokumente zunächst im Belegjournal; die
  Referenzendpunkte beweisen bereits alle vorgesehenen Einstiegskontexte.
- Aufbewahrung, kontrollierte Löschung und Restore bleiben durch `LEG-004`
  und POC-112 zu entscheiden; fehlende Objekte sind bis dahin ein
  diagnostizierbarer Betriebsfehler.
