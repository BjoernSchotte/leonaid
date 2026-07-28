# LeonAid-Personas

Dieses Dokument ist die zentrale, kurze Produktreferenz für alle Menschen,
die LeonAid verwenden, betreiben oder von einer Charity-Aktion betroffen
sind. Es übersetzt die ausführliche Konzeption in konkrete Ziele,
Nutzungskontexte und Zugriffsgrenzen.

Maßgeblich für Details bleiben
[`specs/produkt-und-architekturvorschlag.md`](specs/produkt-und-architekturvorschlag.md)
und der bewiesene PoC-Stand in
[`specs/leonaid-poc/PLAN.md`](specs/leonaid-poc/PLAN.md).

## Pflegevertrag

`PERSONAS.md` wird im selben Task aktualisiert, wenn sich eine Persona, Rolle,
Berechtigung, Navigation, Kernaufgabe oder PoC-Grenze ändert. Ein Task ist
inhaltlich nicht vollständig, wenn seine Produkt- oder Rechteentscheidung
diesem Dokument widerspricht.

Dabei gelten vier Leitplanken:

1. Persona und technische Rolle sind nicht dasselbe. Eine Person kann mehrere
   Rollen besitzen.
2. Aktionsrollen gelten nur für die konkrete Charity-Aktion.
3. Ausgeblendete UI-Elemente ersetzen nie die serverseitige Autorisierung.
4. Aktionsspezifische Rollen erscheinen nur bei passender Capability.

## PoC-Personas

### Charity-Admin

**Ziel:** Eine Charity-Aktion vorbereiten, operativ steuern und
nachvollziehbar abschließen.

**Kontext:** Ehrenamtliches Lions-Mitglied, überwiegend am Desktop und häufig
in kurzen Arbeitsfenstern. Der Charity-Admin verwaltet nur eigene Aktionen.

**Kernaufgaben im PoC:**

- Aktion, Zeitraum, Ziel, Beneficiaries und öffentliche Darstellung pflegen;
- Mitglieder in selbst verwaltete Aktionen einladen;
- Aktionsrollen ausschließlich in selbst verwalteten Aktionen zuweisen und
  entziehen;
- Firmen, Kontakte, Akquisiteure und Mehrfachzuordnungen überblicken;
- interne und öffentliche Bestellungen prüfen;
- Rechnungen nach frischer Anmeldung freigeben;
- Rechnungs-PDF abrufen, versenden und den Versand kontrolliert wiederholen;
- exakte Vollzahlung manuell verbuchen;
- Rechnung begründet stornieren, ohne Beleg oder PDF zu überschreiben;
- auf dem Dashboard aktionsweite Sponsor-Pipeline, Bestellungen,
  Bestellwert, fakturierten Betrag und offene Posten verstehen;
- von jeder Dashboard-Kennzahl in die bereits nach Aktion und Status
  gefilterte Arbeitsliste wechseln.

**Zugriffsgrenze:** `charity_admin` ist eine Aktionsrolle. Sie gibt keine
Rechte auf fremde Aktionen und keine globalen System- oder Finanzrollen. Der
letzte Charity-Admin einer noch operativ veränderbaren Aktion kann nicht
ersatzlos entfernt werden.

**Oberfläche:** Responsive Backoffice-Web-App; einzelne CRM-Aufgaben können
zusätzlich in Twenty stattfinden.

### Akquisiteur

**Ziel:** Firmen oder persönliche Kontakte als Sponsoren gewinnen und den
nächsten Schritt zuverlässig dokumentieren.

**Kontext:** Lions-Mitglied, häufig mobil unterwegs und unterschiedlich
technikaffin.

**Kernaufgaben im PoC:**

- eigene und gemeinsam zugeordnete Firmen oder Personen sehen;
- neuen Sponsor anlegen und bei einem Treffer bestehende Akquisiteure sehen;
- sich nach expliziter Bestätigung zusätzlich zuordnen;
- Kontaktversuch, Ergebnis und Wiedervorlage dokumentieren;
- Bestellung oder Zusage erfassen;
- öffentliche Bestellungen eigener Kontakte unter „Neues“ sehen;
- auf dem persönlichen Dashboard eigene Pipeline, Wiedervorlagen,
  Aktivitäten und den nächsten sinnvollen Schritt sehen;
- Aktionsfortschritt mit Wert, Einheit und verständlichem Text als
  Motivation verfolgen und direkt in eine gefilterte Sponsor-Liste wechseln.

**Zugriffsgrenze:** `acquirer` gilt je Aktion und nur für zugeordnete
CRM-Parteien. Eine Zuordnung eröffnet keinen Zugriff auf Rechnungen,
Finanzdokumente oder Charity-Administration. Akquisiteure erhalten im PoC
keinen eigenen Twenty-Zugang.

**Oberfläche:** Installierbare, mobile-first PWA; sie teilt Komponenten und
Funktionen mit der responsiven Web-App.

### Öffentlicher Besteller oder Sponsor

**Ziel:** Eine Charity-Aktion verstehen und ohne Account eine verbindliche
Bestellung oder Zusage absenden.

**Kontext:** Öffnet einen beworbenen Link oder QR-Code auf Smartphone oder
Desktop und kennt LeonAid vorher nicht.

**Kernaufgaben im PoC:**

- Zweck, Zeitraum und Beneficiaries verstehen;
- Angebot, Preis und Menge auswählen;
- Firma oder persönliche Kontaktdaten sowie Liefer-/Rechnungsdaten angeben;
- Formular gegen Doppelübermittlung geschützt absenden;
- verständliche Bestätigung erhalten.

**Zugriffsgrenze:** Kein LeonAid-Account und kein interner Datenzugriff. Nur
veröffentlichte Aktionsseiten und explizite Formulare sind erreichbar.

**Oberfläche:** Schlanke, barrierearme Astro-Aktionsseite.

### Finanzverantwortlicher oder Schatzmeister

**Ziel:** Ausgangsrechnungen, Versand, Zahlungen und offene Posten verlässlich
prüfen.

**Kontext:** Arbeitet überwiegend am Desktop und benötigt unveränderliche
Belege sowie nachvollziehbare Exporte für weitere Buchhaltungsprozesse.

**Kernaufgaben im PoC:**

- Rechnungsdaten und Typst-PDFs prüfen;
- Freigabe und Versandstatus nachvollziehen;
- offene und bezahlte Rechnungen unterscheiden;
- Zahlungseingang, Storno und Korrekturhistorie kontrollieren.

**Aktueller Rechteschnitt:**

- `finance_reader` – global oder je Aktion – liest Rechnungen,
  Finanzdokumente und Status, darf aber nichts buchen;
- `finance_manager` ist eine globale, nur vom System-Admin vergebbare Rolle
  für Vollzahlung und Storno;
- ein Charity-Admin besitzt dieselben Finanzaktionen ausschließlich in
  selbst verwalteten Aktionen.

Der Golden-Data-Benutzer **Finn Finanzen** ist bewusst `finance_reader` und
beweist den read-only Fall. Für `finance_manager` existiert im PoC noch kein
dauerhaft gepflegter Golden-Login; die Rolle ist technisch vorgesehen.

**Oberfläche:** ERP-light-Bereich der Backoffice-Web-App.

### System-Admin

**Ziel:** Eine einzelne Clubinstallation sicher, verfügbar und
wiederherstellbar betreiben.

**Kontext:** Technisch erfahrenes Lions-Mitglied oder beauftragter Betreiber.
Die Mandantentrennung erfolgt durch getrennte Installationen.

**Kernaufgaben im PoC:**

- Docker-Compose-Deployment, Secrets und Integrationen betreiben;
- Benutzer, globale Rollen, Aktionsrollen und Sitzungen verwalten;
- Twenty, PostgreSQL, RustFS und Mail-Relay konfigurieren;
- katalogisierte Feature-Flags für kontrollierte Rollouts ein- und
  ausschalten sowie deren Revision und Wirkung prüfen;
- Datenschutz-Nachweise und Kontaktsperren zu einer exakten E-Mail-Adresse
  prüfen, eine portable Datenauskunft erzeugen und einen kontrollierten
  Anonymisierungsworkflow ausführen;
- dabei unveränderliche Rechnungsbelege bewusst erhalten und die im PoC noch
  offenen Rechts-, Fristen- und Twenty-Löschentscheidungen sichtbar lassen;
- Updates, Healthchecks, Diagnose, Backup und Restore durchführen.

**Zugriffsgrenze:** `system_admin` ist systemweit und darf deshalb nicht als
alltägliche Fachrolle verwendet werden. Kritische Aktionen benötigen eine
frische Anmeldung und Audit. Feature-Flags verändern Sichtbarkeit oder
Rollout, niemals Rollen- oder Datensatzberechtigungen. Der letzte aktive
System-Admin kann nicht entfernt werden.

**Oberfläche:** Systembereich der Web-App einschließlich geschütztem
Datenschutz-Arbeitsbereich und UI-Prüfkatalog plus versionierte
Docker-/Runbook-Werkzeuge.

## Nachgelagerte oder externe Personas

### Ausfahrer

**Ziel:** Zugewiesene Bestellungen einer Aktion mit wenig
Koordinationsaufwand ausliefern.

**Kontext:** Mobile, aktionsspezifische Persona des Krapfentaxis.

**Spätere Aufgaben:** Tour und Stopps sehen, nur notwendige Lieferdaten
verwenden, Navigation öffnen und Zustellstatus dokumentieren.

**Status:** Nach PoC/MVP zurückgestellt. `driver` ist ausschließlich eine
Aktionsrolle bei aktiver `delivery`-Capability und erscheint beispielsweise
bei Lions Open nicht automatisch.

### Beneficiary-Ansprechpartner

**Ziel:** Die begünstigte Organisation korrekt darstellen und Informationen
zum Aktionsergebnis erhalten.

**Kontext:** Externe Kontaktperson ohne LeonAid-Account.

**Aufgaben:** Stammdaten, Zweckbeschreibung und gegebenenfalls Bildmaterial
zuliefern; Ergebnis entgegennehmen.

**Status:** Stakeholder, keine technische PoC-Rolle.

## Rollen und Geltungsbereich

| Technische Rolle  | Geltungsbereich       | Produktbedeutung                             |
| ----------------- | --------------------- | -------------------------------------------- |
| `system_admin`    | global                | Betrieb, Benutzer und Integrationen          |
| `finance_reader`  | global oder Aktion    | Rechnungen und Finanzstatus lesen            |
| `finance_manager` | global                | Finanzstatus buchen und Storno kontrollieren |
| `charity_admin`   | Aktion                | eigene Charity-Aktion vollständig verwalten  |
| `acquirer`        | Aktion                | zugeordnete Sponsoren akquirieren            |
| `driver`          | Aktion mit `delivery` | spätere Auslieferung                         |

Weitere aktionsspezifische Rollen wie `player`, `tournament_admin`,
`booth_operator` oder `volunteer` werden erst mit den entsprechenden
Capabilities und den nachgelagerten Use-Cases Lions Open beziehungsweise
Weihnachtsmarkt konkretisiert.

### Verwaltung der Rollen

- Nur ein System-Admin darf globale Rollen vergeben oder entziehen.
- Ein System-Admin darf sämtliche für eine Aktion verfügbaren Aktionsrollen
  verwalten.
- Ein Charity-Admin darf ausschließlich Aktionsrollen in selbst verwalteten
  Aktionen verwalten; globale Rollen und fremde Aktionen bleiben sowohl in der
  Oberfläche als auch über direkte API-Aufrufe gesperrt.
- `driver` wird nur angeboten, wenn die konkrete Aktion die
  `delivery`-Capability besitzt. Der produktive Lieferworkflow bleibt im Pilot
  weiterhin zurückgestellt.
- Jede Änderung benötigt eine frisch bestätigte Anmeldung, einen
  Idempotenzschlüssel und die erwartete Revision. Konflikte werden verständlich
  angezeigt und erfolgreiche Änderungen auditiert.
- Rollen wirken ohne erneute Anmeldung ab dem nächsten Request auf Navigation,
  Listen, Exporte und Dokumentzugriff.
- Ein Entzug beendet die Berechtigung, löscht aber weder die historische
  Mitgliedschaft noch bestehende Fachzuordnungen, Aktivitäten, Rechnungen oder
  Dokumentreferenzen.

## Gemeinsame UX-Anforderungen

- Fachbegriffe statt interner IDs, Twenty-Objektnamen oder Technikjargon;
- Status, Konsequenz und nächster Schritt sind ohne Farberkennung verständlich;
- mobile Kernaktionen bleiben mindestens 44 Pixel groß und erreichbar;
- wichtige Admin- und Finanzaktionen verlangen eine frische Anmeldung;
- Light, Dark und System Mode sind gleichwertig;
- Fehler erklären Problem, Auswirkung und mögliche Korrektur;
- historische Finanz- und Aktivitätsdaten bleiben auch nach Rollenwechsel,
  Sperrung oder Archivierung nachvollziehbar.

## Bewiesene Geräte- und Abnahmematrix

Der gemeinsame responsive Code wird nicht nur aus den primären
Nutzungskontexten abgeleitet. POC-102 beweist die kritischen Wege bewusst auf
beiden Gerätegrößen:

| Persona                | Primär nachgewiesen                         | Responsiver Gegencheck               |
| ---------------------- | ------------------------------------------- | ------------------------------------ |
| Charity-Admin          | Desktop-Dashboard und offene Rechnung       | Rechnungsliste auf dem Smartphone    |
| Akquisiteur            | Smartphone-Pipeline und Bestellerfassung    | Bestellerfassung auf dem Desktop     |
| Öffentlicher Besteller | Smartphone-Aktionsseite und Fehlerkorrektur | Desktop bleibt durch Astro responsiv |

Für diese Wege sind Tastaturfokus, Screenreader-Texte, 200 Prozent
Textvergrößerung, mindestens 44 Pixel große mobile Kernaktionen,
WCAG-Automation und reproduzierbare Performancebudgets Bestandteil der
Definition of Done. Der detaillierte Nachweis steht in
[`specs/leonaid-poc/proofs/POC-102.md`](specs/leonaid-poc/proofs/POC-102.md).
