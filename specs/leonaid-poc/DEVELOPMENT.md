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

| Befehl | Zweck |
|---|---|
| `./leonaid bootstrap` | Secrets und gelockte lokale Dependency-Bäume anlegen |
| `./leonaid doctor` | Docker, Compose, Locks, Secrets und Installationen diagnostizieren |
| `./leonaid check` | nicht mutierende Policy-, Format-, Typ- und Unit-Gates |
| `./leonaid test-unit` | schnelle Tests reiner Domain-Logik |
| `./leonaid dev` | vollständigen Corestack starten, ab POC-010 |
| `./leonaid test-integration` | reale abhängige Systeme testen, ab POC-010 |
| `./leonaid test-e2e` | echte Browserjourneys, ab POC-041 |
| `./leonaid seed` | Golden Dataset v1 idempotent einspielen, ab POC-012 |
| `./leonaid reset` | markierte lokale Testumgebung zurücksetzen, ab POC-012 |

Reservierte Befehle scheitern bis zu ihrem Meilenstein bewusst mit Exitcode 64
und nennen den zuständigen Task. Sie geben keinen grünen Scheinerfolg aus.

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

`check` startet standardmäßig nur in einem sauberen Arbeitsbaum und prüft
danach erneut, dass kein Gate Dateien verändert hat. So ist eine vom Check
verursachte Änderung eindeutig diagnostizierbar.
