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

## KLF-030a: Lieferdaten in beiden Bestellpfaden

- [x] Separater normalisierter Lieferkontakt (Name 200, Telefon 40 Zeichen), beide Felder unabhängig optional. Neue Angaben sind Bestandteil des Request-Hashes; leere neue Felder ändern alte Hashes nicht.
- [x] Interner Request unterstützt jetzt die schon bestehende Lieferadresse. Interner und öffentlicher Auftrag speichern identische, serverseitig erzeugte UTC-Fenster-Snapshots und separate Kontakt-Snapshots.
- [x] Pflicht-/Verfügbarkeitsprüfung im geschützten Schreibpfad; öffentlicher Service prüft zusätzlich vor der bestehenden CRM-Auflösung. Keine neuen CRM-Schreibpfade.
- [x] Beide Replay-Pfade und die berechtigte Bestellliste lesen die neuen Angaben. Die bestehende Anonymisierung entfernt den separaten Lieferkontakt.
- [x] Core-Erfassungskontext und öffentliche Alias-/Kampagnenantwort enthalten verfügbare Fenster aus derselben Konfiguration; generierter API-Client aktualisiert.
- [x] 373 Unit-Tests bestanden; Mypy über alle 138 Core-Quelldateien und Ruff bestanden; OpenAPI-Konsistenzprüfung bestanden.
- [x] Isolierter PostgreSQL-Nachweis: physisch gleiche Snapshots für interne/öffentliche Bestellung, getrennte Rechnungs-/Lieferadresse und Kontakt, unvollständiger Entwurf, Pflichtfelder, fremde/unverfügbare IDs, Lesen/Liste, Replay nach Stilllegung und Konflikt bei geänderten Angaben bestanden.
- [x] Ergänzter ASGI-Nachweis für Konfiguration: realer Datenbankadapter, camelCase-Transport, serverseitige UUIDs, no-store, Revisionskonflikte und 401/403/422. Die Identität ist dort synthetisch vorgegeben; echte Anmeldung folgt in den Browsergates.

KLF-030 ist insgesamt noch offen: ein expliziter Abschluss vorhandener Entwürfe fehlt bislang auch im Ausgangscode und wird ergänzt; historische Aufträge, Datenschutz und vollständige HTTP-Bestellungen erhalten weitere Integrationsfälle. Es wurde noch keine geänderte Bestelloberfläche abgenommen.

## KLF-030b: geschützter Entwurfsabschluss

- [x] Berechtigtes Lesen einer Bestellung und expliziter HTTP-Abschluss von `draft` nach `review_ready`; neue Operationen im generierten Client.
- [x] Aktionsmanager dürfen interne Entwürfe abschließen. Akquisiteure benötigen ihre eigene Erfassung und eine weiterhin bestehende Kundenzuordnung. Kundenidentität, Rechnung und serverseitig gespeicherte Positionen/Preise werden beim Abschluss nicht vom Client ersetzt.
- [x] Erneute Pflicht-/Verfügbarkeitsprüfung unter denselben Aktions-/Konfigurationssperren wie die Erstellung. Der einmalige Statusübergang und das inhaltsfreie Audit-Event werden atomar gespeichert.
- [x] Eigener idempotenter Abschlussbefehl: Hash umfasst Aktion, Bestellung, Akteur und normalisierte Lieferangaben. Replay nach Fensterstilllegung funktioniert; andere Daten mit demselben Schlüssel ergeben einen Konflikt.
- [x] Isolierter PostgreSQL-/ASGI-Nachweis: direkte vollständige/unvollständige HTTP-Erstellung, eigenes Lesen, fremder Akquisiteur trotz Kundenzuordnung, fremde Aktionsrolle, Fahrer, ausgeloggter Zugriff, entzogene Kundenzuordnung, fremde Fenster-ID, nicht erlaubte Request-Felder, zwei konkurrierende Abschlussversuche, genau ein Audit-Event, Preis-/Positionsstabilität, Replay und Managerabschluss bestanden. Die Identität ist synthetisch vorgegeben; echte Browseranmeldung bleibt offen.
- [x] 373 Unit-Tests, Mypy über alle 138 Core-Dateien, Ruff und Client-Generierung bestanden. Vollständiger isolierter Konfigurations-/Speichernachweis weiterhin bestanden.

KLF-030 bleibt für historische Aufträge, Datenschutz-Auskunft und öffentliche Service-/HTTP-Regressionsfälle offen. Die sichtbare Erfassungs- und Abschlussoberfläche folgt in KLF-050.

## Sichtprüfung des Ausgangsstands

Die bestehende synthetische Microsite `/campaigns/krapfentaxi-2026/` wurde am 10.09.2026 im In-App-Browser geöffnet und der Lieferadressblock visuell geprüft. Sie enthält noch keine Fensterwahl und keinen separaten Lieferkontakt. Angezeigter Aktionszeitraum: 01.09.–15.11.2026. Die Demo-Einrichtung für Dezember muss deshalb das Aktionsende passend erweitern. Diese Sichtprüfung ist Ausgangsevidenz, kein Nachweis für den neuen Code; die bestehende Instanz wurde nicht verändert.
