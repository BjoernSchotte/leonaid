# Fachstellen-Intake für den LeonAid-Pilot

Dieses Dokument ist die Gesprächsagenda für PILOT-001. Es ersetzt keine
Rechts- oder Steuerberatung. Antworten werden erst nach Bestätigung durch die
genannte Owner-Rolle als kontrollierter Wert und neutrale `EVID-…`-Referenz
in [`DECISIONS.md`](DECISIONS.md) übernommen. Namen, Verträge,
Steuerunterlagen, Kontodaten, Zugangsdaten und vollständige Texte bleiben im
privaten Evidence Store.

## So wird eine Entscheidung geschlossen

Für jeden Punkt werden intern festgehalten:

1. bestätigtes Ergebnis aus den unten genannten zulässigen Werten;
2. zuständige Owner-Rolle und Datum der Bestätigung;
3. neutrale Evidence-ID, zum Beispiel `EVID-TAX-2026-001`;
4. Speicherort des privaten Nachweises außerhalb des Repositories;
5. bei `STOP` der benannte Folge-Milestone.

Die Evidence-ID darf keine Namen, E-Mail-Adressen oder andere
personenbezogene Angaben enthalten.

## Träger und Rechnung

### PILOT-LEG-001 – rechtlicher Träger und Rechnungsaussteller

Owner: rechtlicher Träger  
Spätestes Gate: `pilot-release`

- Welche juristische oder natürliche Person tritt für die Aktion als
  Vertragspartner und Rechnungsaussteller auf?
- Ist bestätigt, dass genau dieser Träger in LeonAid und auf dem Beleg
  erscheinen darf?
- Wo liegt die private Freigabe mit den später in PILOT-044 einzupflegenden
  Stammdaten?

Registerwert nach Bestätigung: `confirmed`.

### PILOT-INV-001 – Pflichtangaben und Freigabeverantwortung

Owner: rechtlicher Träger und Steuerberatung  
Spätestes Gate: `pilot-release`

- Welche Angaben und Rechtstexte müssen auf der konkreten Rechnung stehen?
- Welche Rolle führt die fachliche Vier-Augen-Freigabe durch?
- Wer darf Nummernkreis, Zahlungsziel oder Bank-/Kontaktangaben ändern?

Registerwert nach Bestätigung: `confirmed`.

## Steuer

### PILOT-TAX-001 – Steuerbehandlung

Owner: Steuerberatung und rechtlicher Träger  
Spätestes Gate: `pilot-release`

Zulässiges Ergebnis:

- `small_business`
- `standard_vat`
- `tax_exempt`
- `full_accounting_required` – zwingend Status `stop`

Die Implementierung darf den synthetischen Golden-Data-Steuerfall nicht als
produktive Antwort übernehmen.

### PILOT-INV-002 – E-Rechnungsbedarf

Owner: Steuerberatung und rechtlicher Träger  
Spätestes Gate: `pilot-release`

Zulässiges Ergebnis:

- `not_required`
- `required` – zwingend Status `stop`, weil XRechnung/ZUGFeRD nicht zum
  Pilot-Scope gehören

## Datenschutz

### PILOT-PRIV-001 – Aufbewahrung, Sperre und Löschung

Owner: Datenschutz und rechtlicher Träger  
Spätestes Gate: `pilot-import`

Für Kontakte, Bestellungen, Aktivitäten, Einladungen, Sitzungen,
Rechnungsdaten, PDF-Dokumente, Mail-Metadaten und Audit-Ereignisse sind
jeweils Fristbeginn, Aufbewahrungsfrist, Sperrgrund und erlaubte
Anonymisierung zu bestätigen.

Registerwert nach Bestätigung: `confirmed`. Die konkreten Regeln werden erst
in PILOT-044 autorisiert, versioniert und technisch aktiviert.

### PILOT-PRIV-002 – Rechtsgrundlagen und Informationstexte

Owner: Datenschutz und rechtlicher Träger  
Spätestes Gate: `pilot-release`

- Welche Rechtsgrundlage gilt für importierte Kontakte, Akquiseaktivitäten
  und öffentliche Bestellungen?
- Welche Version des Informationstextes wird wann angezeigt?
- Welche Kanäle müssen bei Widerspruch oder Widerruf gesperrt werden?

Registerwert nach Bestätigung: `confirmed`.

## Betrieb

Owner: Betrieb, soweit nicht anders im Register benannt.

- `PILOT-MAIL-001`: produktiver Relay, Absenderdomain und Domain-Owner;
- `PILOT-OPS-001`: produktive Domain, DNS-Owner und Änderungsweg;
- `PILOT-OPS-002`: VPS-/Hosting-Owner und Zugriffsverantwortung;
- `PILOT-OPS-003`: Backup-Owner, Off-Host-Ziel, RPO und RTO;
- `PILOT-OPS-004`: Secret-Owner, Rotation und Übergabeweg;
- `PILOT-OPS-005`: Monitoring-Owner, Alarmkanal und Erreichbarkeit;
- `PILOT-OPS-006`: Incident-Owner, Stellvertretung und Eskalationsweg.

Zugangsdaten, Provider-Tokens und konkrete Secret-Werte werden niemals in
LeonAid-Formulare oder dieses Register kopiert. Nach Bestätigung ist der
jeweilige Registerwert `confirmed`.

## Pilotgrenze

### PILOT-RUN-001 – Zeitraum und Go/No-Go

Owner: Produktverantwortlicher und Betrieb  
Spätestes Gate: `pilot-deploy`

- Start- und Enddatum des Piloten;
- maximale Anzahl eingeladener Nutzer;
- benannte Go/No-Go-Rolle und Stellvertretung;
- Abbruchkriterien und Zeitpunkt der Entscheidung.

Registerwert nach Bestätigung: `confirmed`.

## Technische Vorprüfung

```sh
./leonaid pilot-doctor --gate pilot-deploy
./leonaid pilot-doctor --gate pilot-import
./leonaid pilot-doctor --gate pilot-release
./leonaid pilot-doctor --gate pilot-release --json
```

Exit-Code `2` bedeutet offene Entscheidung, `3` bedeutet `STOP`. Nur
Exit-Code `0` gibt das gewählte Gate frei.
