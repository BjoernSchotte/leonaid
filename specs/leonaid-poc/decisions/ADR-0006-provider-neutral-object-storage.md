# ADR-0006: Providerneutrale, private und versionierte Dokumentablage

- Status: für den PoC angenommen
- Datum: 2026-07-27
- Entscheider: Produktverantwortlicher und Implementierung
- Referenz: Produkt- und Architekturvorschlag, Kapitel 6, 7.2 und 12.2

## Kontext

Die in POC-091 erzeugten Rechnungs-PDFs müssen unveränderlich, fachlich
zugeordnet und ausschließlich nach Core-Autorisierung abrufbar sein. RustFS
ist die für den PoC gewählte S3-kompatible Ablage, darf aber weder Domain,
Anwendungslogik noch UI an einen konkreten Speicheranbieter koppeln.

Ein erfolgreicher Upload allein genügt nicht: LeonAid muss die tatsächlich
gespeicherte Objektversion, Größe und Prüfsumme kennen. Ein Ausfall des
Speichers darf keinen falschen Erfolgsstatus erzeugen. Ein bereits versandtes
Dokument darf weder ersetzt noch gelöscht werden.

## Entscheidung

### Providerneutraler Port

Der Anwendungsport `ObjectStorage` kapselt:

- privaten, versionierten Bucket sicherstellen;
- unveränderliches Put;
- Head und Get einer exakten Objektversion;
- geschützte Download-Referenz;
- fachlich kontrollierte Löschung einer exakten Version.

Port und Domain kennen ausschließlich Bucket, Object Key, Version-ID,
Medientyp, Größe und SHA-256. Endpunkt, Region, Path-Style und Zugangsdaten
kommen aus der Deployment-Konfiguration. Anbieterklassen bleiben im
Storage-Adapter.

### Private Objekte und Core-Autorisierung

Der Bucket ist privat und versioniert. Die produktive Web/API-Strecke gibt
keine RustFS-URL aus. Charity-Admin und Finanzrolle laden das Dokument über
den Core-Endpunkt; der Core prüft Aktion und Rolle, liest danach genau die
persistierte Objektversion und liefert die Bytes mit `private, no-store`.

Der normale Aufruf ist ein Download-Attachment. `inline=true` verwendet
dieselben autorisierten Bytes als Browser- oder spätere Tauri-Vorschau. Eine
unberechtigte Persona erhält weder Objektbytes, Objektpfad, Prüfsumme noch
signierte URL.

### Dokumentidentität und Immutabilität

`GeneratedDocument` speichert:

- Aktion, Commitment, Rechnung sowie Twenty-Firma und -Kontakt;
- Dokumenttyp, Medientyp und Downloadname;
- Bucket, Object Key und konkrete Version-ID;
- Größe, SHA-256, Render-Version und fachliche Dokumentversion;
- Pending-, Available-, Versand- und Löschzeitpunkte.

Der Object Key ist inhaltsadressiert und enthält Aktion, Rechnung,
Dokumentversion und SHA-256. `If-None-Match` verhindert ein Überschreiben.
Erst nachdem Put, Head/Get und Hashprüfung erfolgreich waren, wird das
Dokument atomar als verfügbar markiert. Datenbank-Constraints und Trigger
schützen die Speicheridentität eines verfügbaren Dokuments sowie sämtliche
Felder eines versandten Dokuments.

### Ausfall und Wiederholung

Die Rechnungsfreigabe legt Rechnung, Pending-Dokument und
`invoice.document.render.requested.v1` in einer Transaktion an. Der Worker
rendert mit dem produktiven Typst-Adapter, speichert über den Port und
vervollständigt erst danach das Dokument.

Ist RustFS nicht erreichbar, bleibt das Dokument `pending`; der
Outbox-Auftrag speichert einen bereinigten Fehler und ist wiederholbar. Bei
einem Retry wird ein bereits verfügbares Dokument nur durch Head/Get der
persistierten Version verifiziert und nicht neu überschrieben.

### Zweite reale Implementierung

RustFS bleibt PoC-Default. Die Contractsuite läuft zusätzlich gegen
[SeaweedFS 4.40](https://github.com/seaweedfs/seaweedfs/releases/tag/4.40)
als eigenständige reale S3-kompatible Implementierung. SeaweedFS gehört nur
zum Testprofil `storage-contract`; es ist keine zweite produktive
PoC-Ablage.

Beide Images sind per Tag und Manifest-Digest gepinnt. Die Tests verwenden
für beide Anbieter denselben produktiven `S3ObjectStorage`-Adapter und
prüfen Put, Head, Get, Version, private Zugriffe, unveränderliches Schreiben
und kontrollierte Löschung.

## Konsequenzen

- Ein Austausch von RustFS betrifft Deployment und Adaptervertrag, nicht
  Fachmodell, UI oder Downloadberechtigung.
- Versand und spätere Dokumentkontexte referenzieren immer eine konkrete
  unveränderliche Objektversion.
- Aufbewahrungs- und Löschfristen bleiben die offene fachlich-rechtliche
  Entscheidung `LEG-004`; bis dahin existiert nur technisch kontrollierte
  Löschung nicht versandter Dokumente.
- Providerseitige Verschlüsselung, externe Backups und Restore werden in den
  Betriebs-Tasks ergänzt; sie ändern den fachlichen Storage-Port nicht.
