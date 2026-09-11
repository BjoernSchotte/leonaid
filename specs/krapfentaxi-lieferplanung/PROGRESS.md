# Implementierungsnachweis

## KLF-010: technischer Abgleich (10.09.2026)

- [x] Draft-PR #3 (`codex/acquisition-delivery-and-beneficiaries`, Stand `85063a7`) read-only untersucht; er ist offen und nicht in diesem Branch enthalten.
- [x] Wiederverwendbar: DST-Prüfung und Überlappungsregeln aus `77618b3`, Grundmuster für Repository/Berechtigungen aus `d3c9379`, später gezielt Bestellintegration und Browserfälle.
- [x] Übernahmeentscheidung: keine vollständige Zusammenführung. Der alte Branch enthält zusätzliche Begünstigtenansichten und historische Rechnungssperren; diese gehören nicht zu diesem Plan. Fenster dürfen im neuen Vertrag auch ungebucht nicht umterminiert, gelöscht oder reaktiviert werden. Krapfentaxi- und Ordering-Prüfung müssen ergänzt werden.
- [x] Vertrag bleibt wie PLAN.md: Manager-Ressource `/delivery-configuration`, UTC-Zeitpunkte in PostgreSQL, lokale Datum-/Uhrzeiteingabe mit IANA-Zeitzone, separate Kontakt-Snapshots, neue UUIDs vom Server. Neue Migration folgt auf `0035_merge_campaign_surveys`.
- [x] Identity-/Acquisition-Code untersucht. Nach fachlicher Klarstellung vom 10.09.2026 verwendet KLF-050 ausschließlich bestehende CRM-Kunden und deren Akquise-Zuordnung; eine Mitglied-zu-CRM-Person-Verknüpfung ist nicht erforderlich.
- [x] Demo-Vorgabe vom Nutzer: Aktion „Krapfentaxi 2026“, zwei Tage im Dezember. Festgelegte synthetische Konfiguration: 04. und 05.12.2026, jeweils 08–10, 10–12 und 12–14 Uhr, Europe/Berlin.
- [x] Lokales Demo-Ziel abgeglichen: `https://localhost:28443`, Krapfentaxi 2026 (`20000000-0000-4000-8000-000000000001`), bestehende Website und veröffentlichte EmDash-Kampagne auf derselben Core-Aktion. Die frühere Instanz auf 19443 bleibt unverändert. Gewählte Dezember-Termine und Kundenablauf in den abschließenden Planstellen nachgezogen.

Die weiteren Aufgaben werden unten einzeln nachgewiesen. Alte Tests aus PR #3 gelten nicht als Nachweis für diesen Branch.

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

KLF-030 ist insgesamt noch offen: der im Ausgangscode fehlende explizite Entwurfsabschluss folgt im nächsten Slice; historische Aufträge, Datenschutz und vollständige HTTP-Bestellungen erhalten weitere Integrationsfälle. Es wurde noch keine geänderte Bestelloberfläche abgenommen.

## KLF-030b: geschützter Entwurfsabschluss

- [x] Berechtigtes Lesen einer Bestellung und expliziter HTTP-Abschluss von `draft` nach `review_ready`; neue Operationen im generierten Client.
- [x] Aktionsmanager dürfen interne Entwürfe abschließen. Akquisiteure benötigen ihre eigene Erfassung und eine weiterhin bestehende Kundenzuordnung. Kundenidentität, Rechnung und serverseitig gespeicherte Positionen/Preise werden beim Abschluss nicht vom Client ersetzt.
- [x] Erneute Pflicht-/Verfügbarkeitsprüfung unter denselben Aktions-/Konfigurationssperren wie die Erstellung. Der einmalige Statusübergang und das inhaltsfreie Audit-Event werden atomar gespeichert.
- [x] Eigener idempotenter Abschlussbefehl: Hash umfasst Aktion, Bestellung, Akteur und normalisierte Lieferangaben. Replay nach Fensterstilllegung funktioniert; andere Daten mit demselben Schlüssel ergeben einen Konflikt.
- [x] Isolierter PostgreSQL-/ASGI-Nachweis: direkte vollständige/unvollständige HTTP-Erstellung, eigenes Lesen, fremder Akquisiteur trotz Kundenzuordnung, fremde Aktionsrolle, Fahrer, ausgeloggter Zugriff, entzogene Kundenzuordnung, fremde Fenster-ID, nicht erlaubte Request-Felder, zwei konkurrierende Abschlussversuche, genau ein Audit-Event, Preis-/Positionsstabilität, Replay und Managerabschluss bestanden. Die Identität ist synthetisch vorgegeben; echte Browseranmeldung bleibt offen.
- [x] 373 Unit-Tests, Mypy über alle 138 Core-Dateien, Ruff und Client-Generierung bestanden. Vollständiger isolierter Konfigurations-/Speichernachweis weiterhin bestanden.

KLF-030 bleibt für historische Aufträge, Datenschutz-Auskunft und öffentliche Service-/HTTP-Regressionsfälle offen. Die sichtbare Erfassungs- und Abschlussoberfläche folgt in KLF-050.

## KLF-030c: Altbestellungen und Datenschutz-Auskunft

- [x] Datenschutz-Auskunft und Export enthalten pro zugehöriger Bestellung die neue Fenster-ID, den gespeicherten Zeitraum und den separaten Lieferkontakt. Die bestehende System-Admin-Berechtigung, E-Mail-Zuordnung und Fresh-Login-Pflicht für den Export bleiben bestehen. Keine zusätzliche Suche oder CRM-Verknüpfung über den Lieferkontakt.
- [x] Vorgänger-Schema `0011_public_orders` mit bestehendem versioniertem Altbestellungs-/Rechnungsfixture geladen, bis `0035` und anschließend über die neue Migration gebracht. Vorher-/Nachher-Vergleich: sämtliche bisherigen Bestellfelder und die Rechnung unverändert; neue Lieferfelder bleiben null. Die Altbestellung bleibt als fakturierte Bestellung mit Positionen und Betrag lesbar.
- [x] Isolierter PostgreSQL-/ASGI-Nachweis für die neue Auskunft: camelCase, no-store, ausschließlich zugehörige Bestellungen, historische null-Werte und 401/403. Der Export-Service liefert dieselben Lieferdaten; dessen bestehender Fresh-Login-HTTP-Schutz wurde nicht verändert.
- [x] Anonymisierung entfernt den Lieferkontakt und anonymisiert die vorhandene Adresse. Historischer Fenster-Snapshot bleibt unverändert. Zusätzliche Anonymisierung des Altbestellers behält die ausgestellte Rechnung vollständig unverändert.
- [x] Vollständiger Liefer-Konfigurations-/Bestell-/Abschlussnachweis weiter bestanden; 373 Unit-Tests, Mypy über 138 Core-Dateien, Ruff und Client-Generierung bestanden.

KLF-030 bleibt für weitere öffentliche Service-/HTTP-Regressionsfälle und den expliziten Replay eines vor der Erweiterung gespeicherten Requests offen. Die neuen Lieferkontakte erhalten keine eigenen Aufbewahrungsfristen; der Nachweis verwendet die bereits vorhandene synthetische Rechtskonfiguration.

## KLF-030d: öffentliche HTTP-Bestellung und Alt-Request-Replay

- [x] `tools/delivery/legacy-replay.json`: synthetische Request-Hashes mit Anwendungscode aus `f12a035`, vor der Liefererweiterung, erzeugt. Zugehörige interne und öffentliche Befehlsnachweise werden vor Migration `0036` gespeichert. Beide aktuellen HTTP-Eingänge liefern nach dem Upgrade dieselbe Bestellung ohne CRM-Zugriff oder weitere Bestellung; neue Kontaktangaben mit demselben Schlüssel erzeugen einen Konflikt.
- [x] Öffentlicher HTTP-Eingang gegen PostgreSQL: fehlendes/fremdes Fenster, unvollständige Adresse, ungültiger Kontakt und vom Client behaupteter Zeitraum vor jedem CRM-Zugriff abgewiesen. Vollständige Bestellung speichert Fenster und Kontakt; öffentliche Bestätigung enthält keine Kontaktwerte.
- [x] Replay nach Stilllegung erhält die ursprüngliche Bestellung, ohne CRM erneut aufzurufen. Neue Bestellung mit stillgelegtem Fenster wird abgewiesen.
- [x] Echte konkurrierende Datenbankänderung während der CRM-Auflösung: wartende Aktionssperre nachgewiesen, laufende Bestellung wird zuerst abgeschlossen, danach Stilllegung gespeichert; die nächste Bestellung wird abgewiesen. Der Test wartet auf PostgreSQLs Lock-Zustand, nicht auf eine angenommene Verzögerung.
- [x] Bestehende Firmenwiederverwendung und Firmenanlage aus der Lieferadresse durch den öffentlichen Service geprüft. Der separate Lieferkontakt wird weder zum CRM-Besteller noch zum Firmenkontakt und erscheint nicht im Audit-Event.
- [x] Vollständiger isolierter Liefernachweis einschließlich Migration, Speicherung, Abschluss, Datenschutz, Alt-Replay und öffentlichem HTTP bestanden. Ruff bestanden. Die externe CRM-Schnittstelle ist in diesen gezielten Serviceprüfungen ein protokollierender Testadapter; echter Twenty-Transport und sichtbare öffentliche Formulare bleiben Teil der späteren Gesamtabnahme.

KLF-030 ist abgeschlossen. Diese Nachweise erklären noch nicht Annas Kundenbestellungen, Astro-/EmDash-Formulare oder die Demo für fertig.

## KLF-040a: Liefereditor in der Aktionsverwaltung

- [x] Krapfentaxi-Vorlage bei der Aktionserstellung auswählbar. Nach Erstellung des Entwurfs folgt direkt derselbe Liefereditor wie in der Verwaltung. Ein leerer Entwurf darf bestehen bleiben.
- [x] Nur Krapfentaxi zeigt den Verwaltungsreiter „Lieferung“. Variable Tage und Zeitfenster, sichtbare Zeitzone, lokale Datum-/Uhrzeitfelder und chronologische Darstellung.
- [x] Gespeicherte Termine sind unveränderlich; Stilllegung ist ausdrücklich beschriftet, reaktivierte oder entfernte Altfenster werden nicht angeboten. Archivierte Aktionen sind schreibgeschützt.
- [x] Revisionskonflikt erhält Eingaben. Der Abgleich übernimmt serverseitige Ergänzungen und lokale neue Fenster beziehungsweise Stilllegungen; eine abweichende Zeitzone wird nicht stillschweigend auf neue Termine angewendet.
- [x] `tools/delivery/admin-browser.mjs` gegen eigene sichtbare Docker-Instanz: echte Anmeldung über Core und lokales Mailpit, Aktionserstellung, sechs Fenster an zwei Tagen, weitere Tage/Fenster, gespeicherte Zeiten, echter paralleler HTTP-Konflikt, Abgleich und Stilllegung bestanden. Synthetische Termine im Jahr 2037; keine bestehende Demo geändert.
- [x] TypeScript-Prüfungen für Features und Web bestanden. Sichtprüfung der automatischen Aufnahmen bei 1440, 390 und 562 Pixeln sowie 200 Prozent Text bei 780 Pixeln; Überlauf korrigiert und Nachprüfung bestanden. Unabhängige Abschlussprüfung: keine offenen Fehler im geprüften Verwaltungsbereich; bestehendes Design beibehalten.
- [x] Bestehende Verwaltungsregression bestanden: API-Vertrag, vier React-Komponententests und vollständiger Browser-Lebenszyklus einschließlich Barrierefreiheit, Dark Mode und mobiler Darstellung. Der Selektor für den nach der Erstellung neu positionierten Verwaltungslink wurde angepasst; individuelle Aktionen werden ausdrücklich ohne Liefereditor geprüft.
- [x] In-App-Browser: Nach ausdrücklich freigegebenem CA-Import echte Anmeldung, Vorlagenwahl, vollständige Krapfentaxi-Erstellung und direkter Übergang in den leeren Liefereditor sichtbar geprüft. In einer synthetischen Testaktion neues Fenster 16–18 Uhr gespeichert, stillgelegt und nach Neuladen als stillgelegt bestätigt. Zeitzone, Tagesgruppen und Eingabefelder visuell kontrolliert.

KLF-040 ist für die Aktionsverwaltung abgeschlossen. Anna und die öffentlichen Bestellformulare sind weiterhin nicht als umgesetzt oder abgenommen markiert.

## KLF-050: Annas Kundenbestellungen in Arbeit

Fachliche Klarstellung vom 10.09.2026: Anna bestellt nie für sich selbst; sie wählt bestehende Kunden aus dem CRM. Die zuvor ergänzte Eigenbestellungs-Erweiterung wird vollständig entfernt, einschließlich eigener Mitgliederverwaltung, API-Vertrag und Migration `0037_member_buyer_link`. In der isolierten lokalen Testinstanz wurde diese ausschließlich synthetische Zuordnung mit dem vorgesehenen Downgrade entfernt; die Lieferplanung in Migration `0036_delivery_windows` bleibt erhalten.

Der Schutz beim Wiederholen einer Kundenbestellung bleibt erhalten: Bestelleigentümer und bestehende Kundenzuordnung werden erneut geprüft. Die entsprechenden Fälle sind in den Liefer-/Abschlusstest übernommen. Erfassung, Lieferanzeige und Entwurfsabschluss befinden sich in Umsetzung; KLF-050 ist noch nicht abgenommen. Scrollleisten werden auf ausdrücklichen Nutzerwunsch unsichtbar gehalten, bei weiterhin funktionierender Scrollbedienung.

Nach der Korrektur erneut bestanden: vollständiger isolierter Liefernachweis (Konfiguration, interne/öffentliche Speicherung, Abschluss, Wiederholungen einschließlich entzogener Kundenzuordnung, Alt-Hashes und Datenschutz), Ruff, Client-Generierung und Features-Typecheck. Die aktualisierten API-, Web- und PWA-Dienste sind lokal gesund. Im In-App-Browser ist bestätigt, dass Annas Mitgliederansicht keine Eigenbestellungs-Einrichtung mehr enthält.

## KLF-050 abgeschlossen: Kundenbestellung und Entwurfsabschluss

- [x] Anna wählt ausdrücklich einen ihr zugeordneten bestehenden CRM-Kunden. Keine Eigenbestellungsoption und keine automatische Auswahl des ersten Kunden. Kunden- und Aktionswechsel setzen die zugehörigen Eingaben zurück; der PWA-Kopf zeigt die tatsächlich ausgewählte Aktion.
- [x] Separate Lieferadresse mit ausdrücklicher Übernahme der Rechnungsadresse; nach Tagen gruppierte Fenster ohne Vorauswahl; Lieferkontakt und Telefonnummer unabhängig optional. Unvollständige Lieferdaten sind als Entwurf möglich, eine teilweise Adresse wird nicht stillschweigend verworfen.
- [x] Echte Stilllegung zwischen Auswahl und Absenden: Fensterliste aktualisiert, ungültige Auswahl entfernt, übrige Eingaben erhalten. Anschließend erfolgreiche Bestellung mit neuem Fenster.
- [x] Gespeicherte Bestellung über ihre URL erneut geladen. Anna und berechtigte Manager schließen Entwürfe über den vorhandenen Abschluss-Endpunkt ab; Besteller, Rechnung, bepreiste Positionen und Betrag bleiben erhalten. Historische Lieferdaten werden aus der Bestellung angezeigt.
- [x] `tools/delivery/orders-browser.mjs` vollständig bestanden gegen die eigene lokale Instanz mit echtem Core, Mailpit und Twenty. Nachgewiesen sind Kundenwechsel, getrennte Adressen, Stilllegung, gespeicherte Kontakte, Entwurfsabschluss durch Anna und Manager sowie mobile Darstellung und Tastaturscrolling ohne sichtbare Scrollleisten. Die Testaktion nutzt ausschließlich synthetische Termine 2037.
- [x] Bestehender `tools/commitments/test.sh`-Lauf erfolgreich: 11 Browserfälle bestanden, 16 gemäß bestehender Projektmatrix übersprungen; neun Browser-/Viewport-Kombinationen geprüft. API, PostgreSQL und Browser stimmen bei Golden-Bestellsummen überein. Eigene isolierte Testressourcen anschließend entfernt.
- [x] In-App-Browser: Kundenbestellung erfasst, gespeichert und erneut geladen; Lieferadresse, Fenster und gesonderter Name mit Telefonnummer sichtbar bestätigt. Dieselben Angaben auch in der mobilen Admin-Bestellliste kontrolliert.
- [x] Desktop, Mobil, Nutzerbreite 499 Pixel und 200 Prozent Text geprüft. Mobile Listenbreite korrigiert; Statusfilter bleibt intern scrollbar. Unabhängige Abschlussprüfungen für Anna und Manager jeweils `ship`, Dokumentationsabgleich erhält die bestehende Gestaltung.

KLF-050 ist abgeschlossen. Öffentliche Formulare und gemeinsame Demo-Abnahme bleiben KLF-060/070.

## Sichtprüfung des Ausgangsstands

### Vorhandene öffentliche Microsite

Die bestehende synthetische Microsite `/campaigns/krapfentaxi-2026/` wurde am 10.09.2026 im In-App-Browser geöffnet und der Lieferadressblock visuell geprüft. Sie enthält noch keine Fensterwahl und keinen separaten Lieferkontakt. Angezeigter Aktionszeitraum: 01.09.–15.11.2026. Die Demo-Einrichtung für Dezember muss deshalb das Aktionsende passend erweitern. Diese Sichtprüfung ist Ausgangsevidenz, kein Nachweis für den neuen Code; die bestehende Instanz wurde nicht verändert.


## KLF-060 abgeschlossen: gemeinsames öffentliches Lieferformular

- [x] Ein gemeinsames Astro-Formular für bestehende Website und EmDash: verfügbare Fenster aus Core, chronologisch nach Tagen gruppiert, keine automatische Auswahl. Lieferkontakt und Telefon sind getrennt optional; Rechnungs- und Lieferadresse bleiben unabhängig.
- [x] Formularschema, Core-Transport und sichere native Fehler-Wiederanzeige um die drei Felder ergänzt. JavaScript lädt nach Fensterkonflikten nur die aktuelle, serverseitig gerenderte Auswahl derselben Aktion und desselben Bestellalias nach. Ohne JavaScript funktioniert weiterhin der normale Formular-POST; erneute Einwilligung nach Fehlern bleibt erforderlich.
- [x] `tools/delivery/public-browser.mjs`: reale Bestellungen über `/krapfentaxi`, `/campaigns/krapfentaxi-2026/` und `/lieferpruefung`, jeweils mit JavaScript und nativem POST. Alle sechs Fälle sowie identische Wiederholung ohne Doppelbestellung bestanden, mit echtem Core, Mailpit und Twenty. Nach einem Test-Klickproblem wurde der native Weg per Tastatur geprüft und der Lauf mit den bereits verifizierten Belegen fortgesetzt; kein künstlicher Reset des Anfragelimits.
- [x] Wirkliche Stilllegung zwischen Auswahl und Absenden sowohl mit JavaScript als auch nativ: keine Bestellung mit dem stillgelegten Fenster, übrige Eingaben und Vorgangs-ID bleiben erhalten, gültige Neuauswahl wird angenommen.
- [x] `tools/delivery/final-checks.mjs`: zusätzlicher Alias aktiv, deaktiviert und auf eine andere Aktion verschoben; ursprüngliches Formular behält seine kanonische Aktionsbindung, manipulierte Bestellalias-/Token-Kombination wird durch Core abgewiesen, keine Bestellung für eine der beiden Aktionen.
- [x] Bestehende öffentliche Bestellregression gegen Core und Twenty erfolgreich, einschließlich Firmenwiederverwendung und bisherigem Verhalten ohne aktivierte Lieferplanung. Sicherer Redisplay-Nachweis und alle 24 Redirect-Vertragsfälle bestanden. Public-/Campaign-Typechecks ohne Fehler.
- [x] Beide fertigen Renderer bei 1440, 390 und 499 Pixeln sowie 780 Pixeln mit 200 Prozent Text geprüft: kein horizontaler Seitenüberlauf, sechs gleichmäßig ausgerichtete Optionen, sichtbare Feldbeschriftungen und optionaler Kontakt. Unabhängige Abschlussprüfung nach einer Abstandskorrektur: `ship`; bestehende Gestaltung beibehalten.
- [x] In-App-Browser: echte öffentliche Bestellung erfolgreich angenommen; Formular und gespeicherte Referenz sichtbar geprüft. Unsichtbare Scrollleisten bei erhaltener Scrollfunktion auch im CMS-Editor geprüft. CMS-Regel direkt in den bestehenden Editor-Einstieg eingebunden, kein zusätzlicher UI-Baukasten.

Die Browserwerkzeuge laufen im gepinnten Playwright-Image im eigenen `edge`-Netz. `/proof` enthält ausschließlich lokale Testbelege, CA und die geprüften Serverzertifikate; diese Dateien werden nicht committed. Der öffentliche Test verwendet die tatsächliche lokale Origin auf Port 28443 und die zugehörigen Zertifikats-Pins. `PUBLIC_PROOF_RESUME=1` setzt einen unterbrochenen Lauf anhand seiner bereits verifizierten Belege fort; der normale Lauf prüft alle Fälle. Die bestehende Anfragengrenze bleibt unverändert.


## KLF-070 abgeschlossen: gemeinsame Demo und Neustart

- [x] `tools/delivery/demo-configuration.mjs` konfiguriert die ausdrücklich ausgewählte lokale Aktion anhand ihrer ID über die regulären Verwaltungs-APIs. Wiederholte Ausführung liefert dieselbe Konfiguration und dieselben Fenster-UUIDs. Sechs aktive Fenster am 04./05.12.2026, jeweils 08–10, 10–12 und 12–14 Uhr, Europe/Berlin; Aktionsende 31.12.2026.
- [x] Alle sechs öffentlichen Varianten und Anna für den bestehenden CRM-Kunden Musterwerk GmbH verwenden dieselbe Aktion und dieselben verfügbaren Fenster. Sieben reale Bestellungen speichern getrennte Rechnungs-/Lieferadresse, Lieferkontakt mit Telefonnummer sowie serverseitige Zeitfenster-Snapshots.
- [x] `tools/delivery/verify-demo.py snapshot` und `check` gegen echte PostgreSQL-/Twenty-Dienste bestanden. Verglichen werden die sieben Bestellungen, deren Fenster, Konfiguration und eine zusätzliche historische Bestellung samt stillgelegtem, zuvor gebuchtem Fenster. SHA-256 des geprüften Datenbestands vor und nach Neustart identisch; sechs öffentliche Kommandobelege vollständig, keine eigene CRM-Person für den Lieferkontakt angelegt.
- [x] Eigene Datenbank sowie API, Worker, PWA, Web und beide öffentlichen Renderer neu gestartet. Alle Gesundheitsprüfungen danach erfolgreich. In-App-Browser bestätigt erneut die sechs aktiven Dezember-Fenster in der Aktionsverwaltung und die veröffentlichte Microsite. Stillgelegte Testfenster bleiben gemäß dem vereinbarten historischen Modell erhalten und sind öffentlich nicht auswählbar.
- [x] Ruff für den abschließenden Python-Nachweis bestanden. Keine neue Abhängigkeit, keine doppelte CMS-Lieferkonfiguration und keine Eigenbestellungsfunktion.

Alle sieben Planpakete sind abgeschlossen. Vorführinstanz: `https://localhost:28443`; Aktion `20000000-0000-4000-8000-000000000001`. Die Microsite ist unter `/campaigns/krapfentaxi-2026/#bestellen` erreichbar, die bisherige Website unter `/krapfentaxi`. Die beschriebenen Nachweise gelten für diese isolierte lokale Instanz und diesen Branch.

Für den Neustartnachweis wird im bestehenden Core-Image das Repository-Verzeichnis `tools` read-only und das lokale Belegverzeichnis als `/proof` eingebunden; Aufrufe: `python -m tools.delivery.verify-demo snapshot` vor und `python -m tools.delivery.verify-demo check` nach dem Neustart. Verbindungsdaten kommen ausschließlich aus der vorhandenen lokalen Compose-Umgebung. Es werden keine Schlüssel, CA-Dateien oder personenbezogenen Laufzeitbelege in den PR aufgenommen.
