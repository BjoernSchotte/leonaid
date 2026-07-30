# PILOT-050 – Synthetischer technischer Nachweis

Stand: 2026-07-30
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

## Cache-freier Remote-CI-Nachweis

Der technische Vertrag wurde auf Commit
`cac3f9833fc2fe206339acdb1221c08e170b2c54` zusätzlich durch den manuell
ausgelösten, cache-freien
[GitHub-Actions-Lauf 30513894673](https://github.com/BjoernSchotte/leonaid/actions/runs/30513894673)
bewiesen. Der Job `Pilot cold rehearsal` (Job-ID `90779482805`) lief vom
`2026-07-30T04:27:00Z` bis `2026-07-30T05:19:50Z` und endete nach 52 Minuten
und 50 Sekunden mit `success`. Auch alle regulären Unit-, Build-, Lint-/Type-,
Security-, Contract-, Integrations- und Browserjobs desselben Laufs waren
terminal grün.

Der Runner entfernte vor dem Bootstrap den gesamten Docker-Buildcache und
belegte einen leeren Zustand. Die vollständige synthetische Generalprobe
erzeugte danach erneut:

- 47 Core-Tabellen, 99 Twenty-Tabellen und drei RustFS-Objekte;
- einen bytegenauen, verschlüsselten Fresh-Volume-Restore mit `RPO=9 s` und
  `RTO=104 s`;
- reale Twenty- und RustFS-Upgrades, einen absichtlichen
  Produktionsmigrationsfehler sowie Recovery und Rollback;
- identische Golden Journeys vor und nach Upgrade sowie nach Rollback in
  Chromium, Firefox und WebKit.

Das veröffentlichte Artefakt `ci-pilot-cold-rehearsal` enthält ausschließlich
`summary.txt`, `rehearsal/summary.json` und `command.log`. Der
Evidence-Sanitizer prüfte im Job den Summenbeleg und anschließend das gesamte
öffentliche Artefakt. Eine unabhängige Prüfung des heruntergeladenen
Artefakts ergab ebenfalls:

```text
ci-artifact-sanitize: OK: 3 Artefakte geprüft, 0 Secret-Vorkommen redigiert
```

Die SHA-256-Prüfsummen des veröffentlichten Standes sind:

```text
c9a87f267907dca8e7516463ad2a95175972f6d01ca3e2cb2d84e75304419d2f  summary.txt
a92e884bb8d11602b11f360e843d762132e8aa73679976d7f68d2e80b7c4d251  rehearsal/summary.json
18569bee42dbf8a00013bd4f2237ebf840b48b1209b8787fa6f6e445dbe608ba  command.log
```

Der JSON-Summenbeleg bleibt bewusst fail-closed: `mode=synthetic`,
`status=passed`, `realServices=true`, `productionReadiness=false`,
`dataset=golden-v1`; die fünf externen Gates bleiben `open`. Der Remote-Lauf
schließt deshalb den technischen Cold-CI-Teilnachweis, aber weder
`PILOT-050` noch die reale Produktionsfreigabe.

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
