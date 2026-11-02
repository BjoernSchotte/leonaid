---
title: Repository und Entwicklungsbefehle
description: Referenz der wichtigsten LeonAid-Verzeichnisse, Toolchains und Wrapperbefehle.
docId: DOC-P036
audience: [dev]
diataxis: reference
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: b157297a8877c2f88787adcc0339b42363342faa
reviewer: Björn Schotte
---

| Pfad                                  | Inhalt                                                                         |
| ------------------------------------- | ------------------------------------------------------------------------------ |
| `src/leonaid/domain`                  | Fachmodelle und Regeln ohne Transportdetails                                   |
| `src/leonaid/adapters`                | PostgreSQL-, Twenty-, Storage- und weitere Adapter                             |
| `src/leonaid/entrypoints`             | FastAPI- und Worker-Einstiege                                                  |
| `src/leonaid/platform`                | geteilte technische Verträge (Navigation, HTTP-Fehlerformat, Worker-Schleifen) |
| `src/leonaid/modules`                 | Fachmodule mit Routen, Jobs und Navigation                                     |
| `src/leonaid/bootstrap`               | statische Modulregistrierung für API und Worker                                |
| `apps/web`, `apps/pwa`, `apps/public` | Admin-, Akquise- und öffentliche Oberflächen                                   |
| `apps/campaign-site`                  | Astro/EmDash-Kampagnendarstellung                                              |
| `apps/docs`                           | diese Starlight-Site und ihre Qualitätsgates                                   |
| `packages/api-client`                 | kanonisches OpenAPI und generierter TypeScript-Client                          |
| `packages/features`, `packages/ui`    | geteilte Funktions- und UI-Bausteine                                           |
| `migrations`                          | Alembic-Revisionsgraph des Core                                                |
| `infra`                               | Compose, Pilot, Locks, Backup, Upgrade und Twenty-Schema                       |
| `tools` / `tests`                     | ausführbare Verträge, Generatoren und Testdaten                                |

Module werden explizit in `src/leonaid/bootstrap/api.py` (Routen, Navigation)
und `src/leonaid/bootstrap/worker.py` (Outbox-Handler, Hintergrundschleifen)
registriert. Der Start bricht bei doppelten Modul-IDs, fehlenden oder zyklischen
Modulabhängigkeiten, kollidierenden Routen, doppelten Handlern und doppelten
Schleifen ab. Weboberflächen eines Moduls registrieren sich in der Web-Shell als
`UiModule` (`packages/features/src/modules.ts`).
`tests/unit/test_architecture_boundaries.py` erzwingt die Importrichtung
`entrypoints → bootstrap → modules → platform`.

`./leonaid bootstrap`, `doctor`, `dev` und `check` bilden den allgemeinen
Entwicklungsweg. `generate-api-client` aktualisiert die API-Artefakte.
`docs-dev`, `docs-check`, `docs-build` und `docs-preview` bearbeiten die
Dokumentation. Feature-Slices verwenden die passenden `test-…`-Befehle.
`./leonaid help` ist die vollständige aktuelle Befehlsreferenz.
