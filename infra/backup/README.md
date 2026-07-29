# Backup, Restore und Disaster Recovery

Dieses Runbook ist der operative Vertrag für den LeonAid-PoC. Es umfasst die
Core-PostgreSQL-Datenbank, die Twenty-PostgreSQL-Datenbank, Twenty lokale
Dateien und das vollständige RustFS-Datenvolume. Restic verschlüsselt jeden
Recovery Point vor dem Transport. Das Ziel muss außerhalb des LeonAid-VPS
liegen.

Nicht gesichert werden Twenty Redis (wiederaufbaubarer Cache/Queue), Mailpit
(lokales Testsystem), Container-Images oder Klartext-Secrets.

## Ziele und Aufbewahrung

| Kennzahl                                   |             PoC-Ziel |
| ------------------------------------------ | -------------------: |
| RPO                                        | höchstens 24 Stunden |
| RTO bis verifizierter Mitgliederoberfläche |  höchstens 2 Stunden |
| tägliche Recovery Points                   |                    7 |
| wöchentliche Recovery Points               |                    5 |
| monatliche Recovery Points                 |                   12 |
| jährliche Recovery Points                  |                    3 |

`backup.sh` wendet diese Rotation nach jeder erfolgreichen Sicherung an und
führt danach `restic check --read-data` aus. Die Produktion plant den Befehl
mindestens täglich und alarmiert bei Ausbleiben oder Fehler. Ein vollständiger
Fresh-Volume-Restore wird mindestens quartalsweise und vor
schemaändernden Upgrades wiederholt.

## Voraussetzungen und getrennte Secrets

Benötigt werden:

- ein von LeonAid unabhängiges Restic-Ziel, zum Beispiel S3-kompatibler
  Object Storage oder SFTP auf einem anderen Host;
- eine lokale Datei mit einem zufälligen Restic-Passwort, Modus `600`;
- optional eine `KEY=VALUE`-Datei, Modus `600`, mit den Zugangsdaten des
  Remote-Backends;
- die normale, nicht versionierte `.env.local`;
- der separat verwaltete Twenty-Integrations-Key.

Restic-Passwort, Remote-Zugang, `.env.local` und Twenty-Key dürfen weder im
Backup-Repository noch im Git-Repository liegen. Sie gehören in den
Secret-Manager beziehungsweise in dessen unabhängige Notfallkopie.

Lokale Pfade werden für produktive Backups hart abgelehnt. Nur das isolierte
Projektpräfix `leonaid-poc112-*` kann mit
`LEONAID_BACKUP_ALLOW_LOCAL_TEST=true` den externen Speicher im
Recovery-Test modellieren.

## Backup ausführen

```sh
export LEONAID_COMPOSE_PROJECT=leonaid
export LEONAID_BACKUP_REPOSITORY='s3:s3.eu-central-1.example.invalid/leonaid'
export LEONAID_BACKUP_PASSWORD_FILE='/secure/leonaid/restic-password'
export LEONAID_BACKUP_CREDENTIALS_FILE='/secure/leonaid/restic-backend.env'
./leonaid backup
```

Der Befehl:

1. validiert Projekt, externes Ziel und Passwortdatei;
2. hält Proxy, APIs, Worker, Frontends und Twenty-Writer kurz an;
3. erzeugt Custom-Format-Dumps beider laufender PostgreSQL-Instanzen;
4. archiviert Twenty-Dateien und das RustFS-Volume im selben Recovery Point;
5. schreibt Manifest, Größen und SHA-256-Prüfsummen;
6. verschlüsselt und überträgt mit dem gepinnten Restic-Image;
7. rotiert, prüft alle gespeicherten Bytes und startet die Writer wieder.

Der kurze Schreibstopp ist die PoC-Konsistenzgrenze zwischen LeonAid, Twenty
und RustFS. Ein fehlgeschlagenes Backup startet die angehaltenen Dienste über
den Exit-Trap ebenfalls wieder.

## Restore in eine frische Umgebung

Der Restore überschreibt nie eine bestehende Compose-Umgebung. Zielnamen
müssen `leonaid-restore-<name>` entsprechen, dürfen keine Container oder
Volumes besitzen und verlangen eine exakte Bestätigung.

```sh
export LEONAID_BACKUP_SOURCE_PROJECT=leonaid
export LEONAID_RESTORE_PROJECT=leonaid-restore-drill-2026-07
export LEONAID_RESTORE_CONFIRM='RESTORE:leonaid-restore-drill-2026-07'
export LEONAID_BACKUP_REPOSITORY='s3:s3.eu-central-1.example.invalid/leonaid'
export LEONAID_BACKUP_PASSWORD_FILE='/secure/leonaid/restic-password'
export LEONAID_BACKUP_CREDENTIALS_FILE='/secure/leonaid/restic-backend.env'
./leonaid restore
```

Der Befehl prüft Restic- und Manifest-Prüfsummen, baut frische Volumes,
restauriert Twenty/RustFS, startet frische PostgreSQL-Container, spielt beide
Dumps ein und startet danach den vollständigen Core-Stack.

## Vollständiger Wiederanlauf

1. Einen Ersatzhost mit Docker/Compose, diesem geprüften Commit und den
   gepinnten Images bereitstellen.
2. `.env.local`, Restic-Zugang und Twenty-Integrations-Key aus dem getrennten
   Secret-Manager einspielen. Keine neuen LeonAid-Verschlüsselungskeys
   erzeugen, da sonst bestehende Sitzungen beziehungsweise geschützte Daten
   nicht lesbar sind.
3. Den Restore mit einem neuen, exakt bestätigten Zielnamen ausführen.
4. `./leonaid doctor` und `docker compose ps` prüfen.
5. Intern zuerst `/_health`, `/health/ready`, Twenty `/healthz` und RustFS
   `/health` prüfen.
6. Dateninventar, Golden-Smoke-Test und Rechnungs-PDF-SHAs prüfen; anschließend
   Anmeldung, Aktion, Bestellung, Dokumentdownload und CRM-Verknüpfung mit
   Testkonten kontrollieren.
7. Erst dann DNS auf die Ersatz-IP umstellen, TLS/Proxy von außen prüfen und
   Schreibzugriffe freigeben. Niedrige DNS-TTL wird vor geplanten Übungen
   gesetzt; die tatsächliche Umschaltzeit wird im Incident protokolliert.
8. Alten Host isoliert lassen, Recovery Point und Logs gegen Löschung
   schützen und Ursache dokumentieren.

Der automatische Nachweis ist:

```sh
./leonaid test-backup
```

Er beginnt mit frischen Systemen, löscht die Quelle nach dem verschlüsselten
Backup und vergleicht den Restore logisch sowie bytegenau. Das lokale
Repository im Test ist ausdrücklich nur ein isoliertes Modell; den
physischen Off-VPS-Standort muss der jeweilige Betreiber zusätzlich durch
seine Remote-Konfiguration und Infrastruktur belegen.

Der Pilot-Gate kombiniert diesen vollständigen Restore mit einem echten
netzgebundenen S3-Backend:

```sh
./leonaid test-pilot-backup
```

Das zusätzliche isolierte RustFS besitzt ein eigenes Netzwerk, Volume und
rotierbare S3-Credentials. Restic initialisiert dort ein echtes
S3-Repository, liest alle verschlüsselten Daten zur Integritätsprüfung und
restauriert sie in ein frisches Ziel. Falsches Passwort, reale
Netzunterbrechung, ein unvollständiger neuester Snapshot und die Rotation der
S3-Zugangsdaten werden fail-closed geprüft. Dieser technische Remote-Vertrag
ersetzt nicht den noch ausstehenden Betreibernachweis, dass das ausgewählte
Produktiv-Repository physisch außerhalb des Pilot-VPS liegt.

## Schemaändernde Migrationen

Schemaändernde Migrationen dürfen nur auf wegwerfbaren PoC-Datenbanken oder
nach einem erfolgreichen `./leonaid backup` ausgeführt werden. Vor der
Produktionsmigration wird der Recovery Point mit `restic check --read-data`
geprüft und mindestens in einer frischen Staging-Umgebung restauriert.

Jede destruktive Vorwärtsmigration referenziert diesen Abschnitt und
beschreibt zusätzlich ihre konkrete Datenüberführung im Modul. Der
CI-Migrationstest beweist weiterhin sowohl den Leeraufbau als auch das Upgrade
eines versionierten Vorgängersnapshots.
