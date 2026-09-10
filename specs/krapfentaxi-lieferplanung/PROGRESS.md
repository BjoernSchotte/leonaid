# Implementierungsnachweis

## KLF-010: technischer Abgleich (10.09.2026)

- [x] Draft-PR #3 (`codex/acquisition-delivery-and-beneficiaries`, Stand `85063a7`) read-only untersucht; er ist offen und nicht in diesem Branch enthalten.
- [x] Wiederverwendbar: DST-Prüfung und Überlappungsregeln aus `77618b3`, Grundmuster für Repository/Berechtigungen aus `d3c9379`, später gezielt Bestellintegration und Browserfälle.
- [x] Übernahmeentscheidung: keine vollständige Zusammenführung. Der alte Branch enthält zusätzliche Begünstigtenansichten und historische Rechnungssperren; diese gehören nicht zu diesem Plan. Fenster dürfen im neuen Vertrag auch ungebucht nicht umterminiert, gelöscht oder reaktiviert werden. Krapfentaxi- und Ordering-Prüfung müssen ergänzt werden.
- [x] Vertrag bleibt wie PLAN.md: Manager-Ressource `/delivery-configuration`, UTC-Zeitpunkte in PostgreSQL, lokale Datum-/Uhrzeiteingabe mit IANA-Zeitzone, separate Kontakt-Snapshots, neue UUIDs vom Server. Neue Migration folgt auf `0035_merge_campaign_surveys`.
- [x] Identity-/Acquisition-Code untersucht: keine bestehende verifizierte Mitglied-zu-CRM-Person-Verknüpfung gefunden. KLF-050 ergänzt diese ausdrücklich und behält die Kunden-Zuordnungsprüfung bei.
- [ ] Online-Demo eindeutig bestimmen und konkrete sechs Fenster bestätigen. Nutzerfrage ist gestellt; keine bestehende Instanz wird aus einer Containerliste als Ziel geraten.

Alle weiteren Aufgaben sind offen. Alte Tests aus PR #3 gelten nicht als Nachweis für diesen Branch. Synthetische Tests können ohne Demo-Angaben umgesetzt werden.
