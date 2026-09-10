# Implementierungsnachweis

## KLF-010: technischer Abgleich (10.09.2026)

- [x] Draft-PR #3 (`codex/acquisition-delivery-and-beneficiaries`, Stand `85063a7`) read-only untersucht; er ist offen und nicht in diesem Branch enthalten.
- [x] Wiederverwendbar: DST-Prüfung und Überlappungsregeln aus `77618b3`, Grundmuster für Repository/Berechtigungen aus `d3c9379`, später gezielt Bestellintegration und Browserfälle.
- [x] Übernahmeentscheidung: keine vollständige Zusammenführung. Der alte Branch enthält zusätzliche Begünstigtenansichten und historische Rechnungssperren; diese gehören nicht zu diesem Plan. Fenster dürfen im neuen Vertrag auch ungebucht nicht umterminiert, gelöscht oder reaktiviert werden. Krapfentaxi- und Ordering-Prüfung müssen ergänzt werden.
- [x] Vertrag bleibt wie PLAN.md: Manager-Ressource `/delivery-configuration`, UTC-Zeitpunkte in PostgreSQL, lokale Datum-/Uhrzeiteingabe mit IANA-Zeitzone, separate Kontakt-Snapshots, neue UUIDs vom Server. Neue Migration folgt auf `0035_merge_campaign_surveys`.
- [x] Identity-/Acquisition-Code untersucht: keine bestehende verifizierte Mitglied-zu-CRM-Person-Verknüpfung gefunden. KLF-050 ergänzt diese ausdrücklich und behält die Kunden-Zuordnungsprüfung bei.
- [x] Demo-Vorgabe vom Nutzer: Aktion „Krapfentaxi 2026“, zwei Tage im Dezember. Festgelegte synthetische Konfiguration: 04. und 05.12.2026, jeweils 08–10, 10–12 und 12–14 Uhr, Europe/Berlin.
- [ ] Online-Demo eindeutig anhand Aktion und URL bestimmen; keine bestehende Instanz wird aus einer Containerliste als Ziel geraten.

Alle weiteren Aufgaben sind offen. Alte Tests aus PR #3 gelten nicht als Nachweis für diesen Branch. Synthetische Tests können ohne Demo-Angaben umgesetzt werden.

Zusätzliche Abnahmevorgabe des Nutzers: jede geänderte Oberfläche sichtbar im In-App-Browser prüfen. Automatische Browserprüfungen ergänzen diese Kontrolle.

## KLF-020: Core-Konfiguration und Migration

- [x] Migration `0036_delivery_windows`: Bestandsaktionen deaktiviert, UTC-Fenster, optionale Auftragsspalten, Composite-FK, Datenbankschutz gegen Löschen, Umterminieren und Reaktivieren.
- [x] Domain-Regeln: variable Anzahl, Zeitzone/DST, Überlappungen, Aktionszeitraum und Verfügbarkeit.
- [x] Manager-GET/PUT einschließlich generiertem OpenAPI-/TypeScript-Vertrag. Neue UUIDs vergibt der HTTP-Eingang; bestehende IDs müssen zur Aktion gehören.
- [x] Repository mit Aktionssperre, Revision und Krapfentaxi-/Ordering-Prüfung. Ausschließlich Stilllegung vorhandener Termine; nach Aktivierung wird über Stilllegung pausiert, damit Abschlüsse die Lieferpflicht nicht versehentlich umgehen.
- [x] Neue Krapfentaxi-Aktion erhält aktivierte Lieferkonfiguration; Aktivierung ohne zukünftige Fenster scheitert. Vorjahreskopie enthält keine Fenster. Änderung des Aktionszeitraums darf aktive Liefertermine nicht abschneiden.
- [x] `./leonaid test-unit`: 369 bestanden. Ruff und Mypy für die betroffenen Core-Dateien bestanden. `./leonaid generate-api-client` erfolgreich.
- [x] `sh tools/delivery/test-foundation.sh`: vollständige Migration und Wiederholung, Bestandsaktion, neue/blank/kopierte Aktionen, sechs UTC-Fenster, konkurrierende Revisionen, Fremd-ID-Rollback, Managerrechte, Aktivierung, Zeitraum-Rollback, Stilllegung und Abbruch einer veralteten SERIALIZABLE-Buchungstransaktion bestanden. Testcontainer ohne Hostports, eigenes Netzwerk-Namespace und vollständige Entfernung danach.

Die HTTP-Browserabnahme der neuen Konfiguration folgt mit KLF-040; es gibt in diesem Slice noch keinen neuen sichtbaren Editor. KLF-030 bindet die neuen Auftragsspalten in die Schreib-/Lesepfade ein.
