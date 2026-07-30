# LeonAid PoC – Development Guide

## Grundsatz

Für den PoC wird nur Docker vorausgesetzt. Python, uv, Node, Bun, Typst,
Playwright und alle Projektpakete laufen in den Versionen und Images aus
`.tool-versions` sowie `infra/locks/external-systems.lock`. Lokale globale
Installationen sind weder erforderlich noch maßgeblich.

Unter macOS ist OrbStack die empfohlene Docker-Umgebung. Nach einem frischen
Checkout:

```sh
./leonaid bootstrap
```

Der Befehl erzeugt einmalig eine nicht versionierte `.env.local`, installiert
beide gelockten Paketwelten und führt `doctor` aus. Er überschreibt keine
vorhandenen Secrets.

## Einheitliche Befehle

| Befehl                          | Zweck                                                                       |
| ------------------------------- | --------------------------------------------------------------------------- |
| `./leonaid bootstrap`           | Secrets und gelockte lokale Dependency-Bäume anlegen                        |
| `./leonaid doctor`              | Docker, Compose, Locks, Secrets und Installationen diagnostizieren          |
| `./leonaid check`               | nicht mutierende Policy-, Format-, Typ- und Unit-Gates                      |
| `./leonaid generate-api-client` | OpenAPI-Dokument und TypeScript-Client deterministisch regenerieren         |
| `./leonaid test-unit`           | schnelle Tests reiner Domain-Logik                                          |
| `./leonaid dev`                 | vollständigen Corestack bauen und bis zur Readiness starten                 |
| `./leonaid test-integration`    | Compose, Reset, ASGI, Migrationen und Outbox aus leeren Volumes real testen |
| `./leonaid test-e2e`            | alle implementierten echten Browserjourneys ausführen                       |
| `./leonaid test-typst`          | Rechnungs-PDFs mit realem Typst, PostgreSQL und zwei PDF-Engines prüfen     |
| `./leonaid test-operations`     | echte Abhängigkeitsausfälle, sichere Logs und Admin-Job-Retry prüfen        |
| `./leonaid seed`                | Twenty provisionieren und Golden Dataset v1 idempotent einspielen           |
| `./leonaid snapshot [NAME]`     | geheimnisfreien kanonischen Systemzustand schreiben                         |
| `./leonaid reset`               | markierte lokale Testumgebung sicher zurücksetzen                           |

Weitere fachlich geschnittene Nachweisbefehle zeigt `./leonaid help`.

## Core-Migrationen

Der API-Container führt beim Start `alembic upgrade head` aus und startet
Uvicorn erst nach einer erfolgreichen Migration. Migrationen liegen unter
`migrations/`; ihre Vorwärtsrichtung darf keine destruktive Änderung ohne
explizite Datenmigrations- und Backup-Referenz enthalten.

`tools/schema/test.sh` beweist den Leeraufbau und das Upgrade des versionierten
Vorgänger-Snapshots gegen echtes PostgreSQL. Der Test ist außerdem Bestandteil
von `./leonaid test-integration`.

## Durable Jobs und Outbox

Der `worker`-Service verarbeitet die transaktionale PostgreSQL-Outbox. Ein
Application Service schreibt Fachänderung, Audit, Befehlsnachweis und
Outbox-Event in derselben Unit of Work. Der Worker beansprucht fällige Jobs mit
`FOR UPDATE SKIP LOCKED` sowie einem Claim-Token; nur der aktuelle Claim darf
Erfolg oder Fehler speichern.

Retry verwendet exponentiellen Backoff bis zum sichtbaren Dead-Letter-Status.
Der operative CLI-Einstieg unter
`python -m leonaid.entrypoints.worker.outbox` bietet `status`, `retry`,
`run-once` und `run-until-idle`. Der manuelle Wiederanlauf speichert Zeitpunkt,
Operator und Zähler. Produktive Autorisierung für diese Operation wird mit den
Admin- und Rollen-Tasks ergänzt; der PoC-022-Nachweis verwendet den isolierten
Operator `poc022-operator`.

`tools/outbox/test.sh` beendet einen echten Producer nach dem Commit, startet
zwei konkurrierende Worker-Container und stoppt Mailpit real, um Retry, Dead
Letter und Wiederanlauf ohne Mock-Server zu beweisen.

Der für System-Admins geschützte Betriebsbereich unter `/admin/system` zeigt
den Dead-Letter-Arbeitsvorrat sowie Live-Signale und Metriken. Sein
Health-, Korrelations-, Datenschutz- und Retry-Vertrag steht in
`infra/observability/README.md`; `./leonaid test-operations` stoppt die drei
Abhängigkeiten real und wiederholt einen echten Mailjob über Chromium.

## OpenAPI und TypeScript-Client

FastAPI ist der Owner des HTTP-Vertrags. Alle Operationen besitzen eine
explizite `operationId`, Response-Schemas und das einheitliche
`ApiErrorResponse`-Schema. `./leonaid generate-api-client` schreibt daraus
`packages/api-client/openapi.json` und
`packages/api-client/src/generated.ts`.

Beide Dateien werden committed, aber nie manuell editiert. `./leonaid check`
regeneriert im Prüfmodus, typprüft das Package und verbietet direkte
`fetch("/api/...")`-Aufrufe sowie direkte Imports des generierten
Transportartefakts aus Frontend-Code. Web, PWA, Public Web, gemeinsame
Features und eine spätere Tauri-App importieren ausschließlich
`@leonaid/api-client`.

Der Breaking-Change-Gate vergleicht Pull Requests mit dem OpenAPI-Dokument des
Base-Commits. Entfernte Pfade, Operationen, Erfolgsantworten, Schemas oder
Properties sowie neue Pflichtfelder und geänderte Typverträge scheitern. Eine
Ausnahme benötigt exakte Alt-/Neu-SHA-256, die vollständige maschinenlesbare
Änderungsliste und eine Begründung in
`specs/leonaid-poc/openapi-breaking-approvals.json`.

## Typst-Rechnungen

Der Core-Container enthält die digest-gepinnte Typst-Laufzeit. Der produktive
Adapter rendert die JSON-Snapshots aus
`tests/fixtures/golden/v1/documents/` mit der versionierten Vorlage
`invoice-v1.typ`.

```sh
./leonaid test-typst
```

Der Test startet echte Systeme aus leeren Volumes, exportiert die
Rechnungssnapshots aus Core-PostgreSQL, rendert jede Rechnung zweimal ohne
Netzwerk und prüft Inhalt, Metadaten, eingebettete Schriften und freigegebene
Layoutbilder mit pypdf und MuPDF. Nachweise landen ignoriert unter
`.artifacts/poc091/`.

Eine absichtliche Vorlagenänderung wird zuerst als Kandidat gerendert:

```sh
LEONAID_TYPST_APPROVAL_CANDIDATE=1 ./leonaid test-typst
```

Dieser Modus aktualisiert die versionierten Referenzbilder nie automatisch.

## Secrets

`.env.example` enthält ausschließlich Generierungstokens. `bootstrap` ersetzt
sie mit kryptografisch zufälligen Werten aus Pythons Standardbibliothek,
schreibt `.env.local` mit lokalen Dateirechten und überschreibt sie nie.
`doctor` lehnt Vorlagenwerte, ein fehlendes Git-Ignore oder versehentlich
versionierte Secrets ab.

Produktive Secrets werden weder aus `.env.local` übernommen noch in Git
verwaltet. Die spätere Deployment-Dokumentation definiert den produktiven
Secret Store separat.

## Editor und Formatierung

`.editorconfig` ist die editorübergreifende Grundlage. Für VS Code sind
empfohlene Extensions, Formatierung, Analysepfade und Tasks in `.vscode/`
versioniert. Speichern darf formatieren; das verbindliche Gate ist dennoch
`./leonaid check` im Container.

Python:

- Ruff formatiert und lintet.
- mypy läuft im strikten Modus gegen `src/`.
- pytest trennt Unit-, Integration-, Contract- und E2E-Stufen.

TypeScript:

- Prettier und TypeScript sind exakt im Bun-Lock.
- App-spezifische Lint-, Typecheck- und Build-Kommandos werden mit den
  jeweiligen App-Slices ergänzt.

## Debug-Profile

VS Code enthält diese Profile:

- **API: Attach to Docker** verbindet sich mit `debugpy` auf Port 5678, sobald
  der API-Dev-Service ab POC-010 mit dem Profil `debug` läuft.
- **PWA: Chromium** und **Public Web: Chromium** öffnen die über den Reverse
  Proxy bereitgestellten Dev-URLs, sobald der Corestack verfügbar ist.

Die Profile starten keine zweite, vom Compose-Stack abweichende
Anwendungsinstanz. Dadurch bleiben Konfiguration, Datenbank und
Fremdsystempfade identisch zu Integration und E2E.

## Fehlerdiagnose

`doctor` nennt für jeden Fehler eine konkrete Korrektur. Typische Fälle:

- Docker-Daemon nicht erreichbar: OrbStack/Docker Desktop starten.
- `.env.local` fehlt oder enthält Tokens: lokale Datei löschen und
  `./leonaid bootstrap` ausführen.
- `.venv` oder `node_modules` fehlt: `./leonaid bootstrap` erneut ausführen.
- Lock-Parität verletzt: den Update-PR vollständig aktualisieren; keine
  manuelle Installation mit ungebundenen Versionen.

## Backup und Recovery

`./leonaid backup` und `./leonaid restore` verwenden ausschließlich die
gepinnten PostgreSQL-, Alpine-, Python- und Restic-Images. Die erforderlichen
Remote- und Bestätigungsvariablen sowie das vollständige Notfallverfahren
stehen in [`infra/backup/README.md`](../../infra/backup/README.md).

`./leonaid test-backup` führt den destruktiven Ablauf nur in den isolierten
Projekten `leonaid-poc112-source` und `leonaid-restore-poc112` aus. Er löscht
die Quell-Volumes und beweist den Restore gegen echte Systeme und Golden Data.

`check` startet standardmäßig nur in einem sauberen Arbeitsbaum und prüft
danach erneut, dass kein Gate Dateien verändert hat. So ist eine vom Check
verursachte Änderung eindeutig diagnostizierbar.
