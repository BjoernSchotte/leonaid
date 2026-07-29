# PILOT-050 – Synthetischer technischer Nachweis

Stand: 2026-07-29  
Ergebnis: Die vollständige Krapfentaxi-Generalprobe ist auf realen,
isolierten Diensten und aus leerem Zustand technisch bewiesen. Sie ersetzt
bewusst nicht die noch offenen externen Provider-, Echtdaten-, Betreiber- und
Fachfreigaben und erklärt daher keine Produktionsbereitschaft.

## Implementierter Vertrag

- `./leonaid test-pilot-rehearsal --synthetic` ist der explizite,
  reproduzierbare Modus für die technische Generalprobe.
- Der Aufruf ohne `--synthetic` bleibt fail-closed. Er weist auf die real
  erforderlichen Provider-, DNS-, Echtdaten-, Betreiber- und Freigabeschritte
  hin, statt eine synthetische Probe als produktionsbereit auszugeben.
- `tools/pilot_rehearsal/contract.py` akzeptiert nur den vollständigen
  Schrittsatz, alle drei Browser-Engines, reale Dienste,
  `productionReadiness: false` und die explizit offenen externen Gates.
- Der Evidence-Sanitizer prüft den JSON-Beleg vor seiner Verwendung.
- Alle Teiltests verwenden eigene Compose-Projektnamen. Die Probe entfernt
  ihre Container, Netzwerke und Volumes auch bei Fehlern.

## Vollständige technische Generalprobe

Ausgeführt:

```text
./leonaid test-pilot-rehearsal --synthetic
```

Ergebnis:

```text
pilot-rehearsal-evidence: OK: sanitized synthetic scope and external gate
boundary verified
pilot-rehearsal-test: OK: vollständige synthetische
Krapfentaxi-Generalprobe
pilot-rehearsal-test:     auf realen Diensten, leerem Zustand und drei
Browsern
```

Der Lauf dauerte von `2026-07-29T14:37:06Z` bis
`2026-07-29T15:14:00Z` und durchlief ohne Mocks:

1. Benutzeradministration mit Identität, Einladung, Login, Rollen,
   Sperrung, E-Mail-Korrektur und Sessionentzug;
2. den echten Golden-XLSX-Import nach Twenty einschließlich Idempotenz und
   Konfliktbehandlung;
3. SMTP-Zustellung und reale Fehlerzustände;
4. Aufbau der produktionsähnlichen Topologie aus leerem Zustand;
5. verschlüsseltes Cross-System-Backup und Restore in frische Volumes,
   einschließlich S3-/Restic-Netzwerk-, Passwort-, Rotations- und
   Snapshotfehlern;
6. Prometheus- und Alertmanager-Ausfälle sowie Recovery für Twenty, RustFS,
   Mail, Worker, Backupalter und Plattenkapazität;
7. Rechtsgrundlagen-, Datenschutz- und Vier-Augen-Konfiguration;
8. Release, reales Twenty-/RustFS-Upgrade, absichtlichen
   Produktionsmigrationsfehler und zweimaligen Rollback;
9. die vollständige Krapfentaxi Golden Journey vor dem Upgrade, nach dem
   Upgrade und auf dem final zurückgerollten Stand jeweils in Chromium,
   Firefox und WebKit bei 390 Pixel Breite.

Die Krapfentaxi-Journey umfasst Einladung und passwortlosen Login,
Akquisiteur-PWA, Sponsor und Twenty-Zuordnung, interne Zusage, öffentliche
Bestellung, Aktivitätsfeed, Rechnungsfreigabe, echtes Typst-PDF,
E-Mail-Versand, Zahlung und Dashboard. Nach Upgrade und Rollback stimmt das
normalisierte Fachresultat bytegenau überein.

Der lokale, ignorierte Summenbeleg liegt unter
`.artifacts/pilot050-synthetic/summary.json`. Er enthält keine Echtdaten und
weist ausdrücklich aus:

```text
mode: synthetic
realServices: true
productionReadiness: false
browsers: chromium, firefox, webkit
status: passed
```

Nach dem Lauf waren keine `pilot050`-Container, -Volumes oder -Netzwerke mehr
vorhanden.

## Sichtbarer In-App-Browser-Nachweis

Im laufenden Entwicklungsstack wurden am selben Stand sichtbar geprüft:

- Mitgliederübersicht und aktionsbezogene Rollenverwaltung;
- Bestellarbeitsvorrat mit internen und öffentlichen Krapfentaxi-Bestellungen;
- Rechnungsjournal mit offenen, bezahlten und stornierten Belegen;
- öffentliche `/krapfentaxi`-Seite mit Angebot, Bestellformular,
  Datenschutzhinweis, Begünstigten und Aktionsziel.

Es traten keine Browserwarnungen oder -fehler auf. Die angemeldete
Charity-Admin-Persona besitzt im sichtbaren Entwicklungsstack keine aktive
Akquisiteur-Zuordnung. Dieser korrekte Leerzustand wird nicht als
Akquisiteur-Beweis gewertet; die vollständige Akquisiteur-Strecke ist durch
die oben genannte Drei-Browser-Journey belegt.

## Bewusst offene Produktionsgrenzen

Der Summenbeleg führt diese Gates ausdrücklich mit Status `open`:

- `real-mail-provider`: echter Mailprovider einschließlich DNS,
  Bounce-/Complaint-Prozess und Operatorhandlung;
- `public-dns-tls`: öffentliche Zieladresse und produktives TLS;
- `controlled-private-import`: rechtmäßig verwendbarer, kontrollierter
  Pilotdatensatz und private Evidence;
- `independent-operator-restore`: Restore ohne Implementiererhilfe;
- `legal-and-tax-approval`: bestätigte Träger-, Steuer-, Bank- und
  Datenschutzwerte.

Zusätzlich fehlen der private reale Summenproof sowie die formale
P0/P1-/P2-Pilotentscheidung. `PILOT-050` und
`./leonaid test-pilot-rehearsal` ohne Modus bleiben deshalb offen.
