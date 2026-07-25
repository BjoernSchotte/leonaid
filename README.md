# LeonAid — Charity-Verwaltung für Service Clubs

Open-Source-Plattform für die Charity-Arbeit von Service Clubs. Der aktuelle
PoC bildet als ersten Baustein die verteilte Sponsoren-Akquise ab.
Ersetzt die bisherigen, manuellen Excel-Listen.

- **Orga-Team** (2 Personen) arbeitet im **Twenty CRM** (Web/Desktop): Kampagnen anlegen,
  Excel importieren, Sponsoren den Mitgliedern zuweisen, Auswertung.
- **Club-Mitglieder** nutzen eine schlanke **PWA** auf dem Handy-Homescreen:
  ihre persönliche Anrufliste sehen, anrufen, Status abhaken, Notiz erfassen,
  neuen Kontakt anlegen. Bewusst seniorengerecht (große Buttons, ein Login per Magic-Link).

## Status

🟡 **Design-Phase.** Dieses Repo enthält aktuell die Architektur-Entscheidung.
Noch kein Code.

## Dokumente

- [Architektur & Design](docs/architektur.md) — die maßgebliche Grundlage (Architektur,
  Datenmodell, Auth-Flow, BFF-API, Hosting, Aufwand, Risiken, Roadmap, Entscheidungslog).

## Eckdaten der Lösung (Kurzfassung)

| | |
|---|---|
| **Backend** | [Twenty CRM](https://github.com/twentyhq/twenty) (Open Source, AGPL-3.0), self-hosted |
| **Mitglieder-Frontend** | Eigene PWA (Vite/React) auf dem Handy-Homescreen |
| **BFF** | Python / FastAPI + httpx — Tooling: `uv`, `ruff`, `mypy`, `pytest`, CI |
| **Login (Mitglieder)** | Magic-Link per E-Mail, 6-stelliger Code als Fallback |
| **Hosting** | Hetzner (EU → DSGVO-sauber), Docker Compose, TLS via Caddy |
| **Team** | 2 Personen (Infra/Backend + Frontend/UX) |
| **Aufwand MVP** | ~20–29 Personentage (inkl. Tests/CI) |

## Warum nicht Twenty direkt am Handy?

Twenty hat **keine native Mobile-App und keine produktive PWA** (kein Service Worker,
unreife mobile Bedienung, zu kleine Touch-Ziele). Twentys eigener Login kann zudem nur
Passwort/SSO — beides ungeeignet für ältere Mitglieder. Deshalb: Twenty als unsichtbares
Backend, davor eine eigene, bewusst einfache PWA. Details siehe Architektur-Doc.
