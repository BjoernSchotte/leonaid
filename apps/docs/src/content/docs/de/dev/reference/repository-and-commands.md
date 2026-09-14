---
title: Repository und Entwicklungsbefehle
description: Referenz der wichtigsten LeonAid-Verzeichnisse, Toolchains und Wrapperbefehle.
docId: DOC-P036
audience: [dev]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

| Pfad                                  | Inhalt                                                   |
| ------------------------------------- | -------------------------------------------------------- |
| `src/leonaid/domain`                  | Fachmodelle und Regeln ohne Transportdetails             |
| `src/leonaid/adapters`                | PostgreSQL-, Twenty-, Storage- und weitere Adapter       |
| `src/leonaid/entrypoints`             | FastAPI- und Worker-Einstiege                            |
| `apps/web`, `apps/pwa`, `apps/public` | Admin-, Akquise- und öffentliche Oberflächen             |
| `apps/campaign-site`                  | Astro/EmDash-Kampagnendarstellung                        |
| `apps/docs`                           | diese Starlight-Site und ihre Qualitätsgates             |
| `packages/api-client`                 | kanonisches OpenAPI und generierter TypeScript-Client    |
| `packages/features`, `packages/ui`    | geteilte Funktions- und UI-Bausteine                     |
| `migrations`                          | Alembic-Revisionsgraph des Core                          |
| `infra`                               | Compose, Pilot, Locks, Backup, Upgrade und Twenty-Schema |
| `tools` / `tests`                     | ausführbare Verträge, Generatoren und Testdaten          |

`./leonaid bootstrap`, `doctor`, `dev` und `check` bilden den allgemeinen
Entwicklungsweg. `generate-api-client` aktualisiert die API-Artefakte.
`docs-dev`, `docs-check`, `docs-build` und `docs-preview` bearbeiten die
Dokumentation. Feature-Slices verwenden die passenden `test-…`-Befehle.
`./leonaid help` ist die vollständige aktuelle Befehlsreferenz.
