# PILOT-041 – Externes Backup und isolierter Restore

Task-ID: `PILOT-041`

Nachweisdatum: 30. Juli 2026

Status: technischer Recovery-, S3- und Operator-CLI-Vertrag bewiesen,
Betreiberdrill offen

## Ergebnis

Der Pilot kombiniert zwei reale, komplementäre Verträge:

1. `tools/backup/test.sh` sichert Core-PostgreSQL, Twenty-PostgreSQL,
   Twenty-Dateien und RustFS-Objekte gemeinsam, löscht die Quelle und
   restauriert alles in frische Compose-Volumes.
2. `tools/pilot_backup/test.sh` überträgt ein vollständiges Recovery-Manifest
   verschlüsselt in ein separat gestartetes, netzgebundenes RustFS-S3-Ziel.
3. `tools/pilot_deployment/test.sh` führt den produktionsnahen Operatorweg mit
   vollem Doctor, echtem S3-Backup und buildfreiem Restore in ein unabhängiges
   Zielprojekt aus.

Der neue zentrale Manifestprüfer verlangt exakt alle vier
Cross-System-Bestandteile. Ein Manifest, das nur die tatsächlich vorhandenen
Dateien aufzählt, kann einen fehlenden Dump oder ein fehlendes Volume-Archiv
nicht mehr verbergen. Größe und SHA-256 jedes Bestandteils werden vor dem
Erstellen von Restore-Volumes geprüft.

Der Backup-Zeitstempel entsteht im Docker-Laufzeitkontext. Damit kann ein
Host-/VM-Uhrversatz kein scheinbar zukünftiges Backup erzeugen; der
Deployment Doctor prüft das resultierende Alter weiterhin gegen maximal
26 Stunden.

## Vollständiger Recovery-Nachweis

```text
backup-manifest-test: OK: vollständiges Inventar sowie drei reale
Negativmutationen bewiesen
backup-inventory: OK: 44 Core-Tabellen, 99 Twenty-Tabellen,
3 RustFS-Objekte
backup-manifest: OK: vier Cross-System-Bestandteile bytegenau
backup-inventory: OK: Restore ist logisch und bytegenau identisch
snapshot-check: OK: golden
1 passed in Chromium
backup-test: OK: verschlüsselter externer Zielvertrag, vollständiger
Fresh-Volume-Restore, PDF-SHAs, Sitzungen, Audit, Outbox, Twenty und
RPO=10 s/RTO=146 s bewiesen
```

Der Test weist ein falsches Restic-Passwort, ein lokales Produktivziel und
eine falsche Restore-Bestätigung ab. Ein vorhandener Zielcontainer oder ein
vorhandenes Zielvolume blockiert den Restore vor dem Download. Private
Golden-Daten sind im verschlüsselten Repository nicht als Klartext
auffindbar.

## Netzgebundener S3-Nachweis

```text
pilot-backup-test: OK: echtes S3/Restic, falsches Passwort,
pilot-backup-test:     Netzunterbrechung, unvollständiger Snapshot und
pilot-backup-test:     rotierte Zugangsdaten fail-closed bewiesen
```

Dieser Test verwendet keine Test-Doubles:

- gepinntes RustFS stellt eine echte S3-API in einem separaten Netzwerk und
  Volume bereit;
- Boto3 legt den echten Bucket an;
- das gepinnte Restic initialisiert das Repository, sichert, liest alle
  verschlüsselten Packs und restauriert in ein leeres Ziel;
- ein falsches Passwort erzeugt einen echten Entschlüsselungsfehler;
- ein gestopptes RustFS erzeugt einen realen, auf 15 Sekunden begrenzten
  Netzwerkfehler;
- ein neuer unvollständiger Snapshot wird als `latest` restauriert und
  fail-closed als unvollständig erkannt;
- RustFS wird mit neuen Root-S3-Credentials gegen dasselbe Datenvolume neu
  gestartet; Restic kann das Repository nur mit den rotierten Credentials
  erneut lesen;
- Secret-Canaries erscheinen weder im Passwort- noch im Netzwerkfehler.

Nach den Tests waren jeweils null Container, Netzwerke und Volumes der
Projekte `leonaid-poc112-source`, `leonaid-restore-poc112` und
`leonaid-pilot041-s3` vorhanden.

## Manifestgebundener Operator-Nachweis

```text
pilot-doctor: OK (pilot-backup): Deployment und Entscheidungen sind freigegeben
backup: OK: leonaid-production-test konsistent, verschlüsselt und
integritätsgeprüft
pilot-backup: OK: leonaid-production-test ist verschlüsselt gesichert und
das Doctor-Manifest ist aktuell
backup-manifest: OK: vier Cross-System-Bestandteile bytegenau
restore: OK: leonaid-production-test wurde nach
leonaid-restore-pilot-operator wiederhergestellt
pilot-restore: OK: leonaid-production-test wurde buildfrei nach
leonaid-restore-pilot-operator restauriert
pilot-deployment-test: OK: Operator-Backup/Restore erhält vier reale
Datenkomponenten
```

Der positive Durchlauf legt eindeutige Probe-Daten in Core PostgreSQL,
Twenty PostgreSQL, dem RustFS-Volume und dem Twenty-Dateivolume an. Nach dem
Restore werden alle vier Inhalte im frischen Zielprojekt geprüft. Ein zu
kurzes/falsches Passwort und eine falsche `RESTORE:<ziel>`-Bestätigung werden
vorher negativ bewiesen. Der Restore verwendet ausschließlich
`--no-build --pull missing`.

Nach dem Volltest waren null Container der Projekte
`leonaid-production-test`, `leonaid-restore-pilot-operator` und
`leonaid-pilot-operator-backup` vorhanden. Die zugehörigen Testnetzwerke,
Volumes und lokal gebauten Release-Images wurden ebenfalls entfernt.

## Offene formale Gates

PILOT-041 bleibt formal offen:

- PILOT-040 ist ohne öffentliche Stagingdomain noch nicht formal
  abgeschlossen.
- Das ausgewählte Produktiv-Repository und seine physische Off-VPS-Lage
  benötigen einen Betreiberbeleg.
- Backupfehler müssen über die reale Alarmkette aus PILOT-042 zugestellt
  werden.
- Ein Operator muss den dokumentierten Restore ohne Implementiererhilfe
  durchführen und das private Protokoll freigeben.

Der isolierte S3-Dienst beweist Netzwerk-, S3-, Verschlüsselungs- und
Credential-Verhalten, ersetzt aber ausdrücklich nicht den physischen
Off-VPS- und Operatornachweis.
