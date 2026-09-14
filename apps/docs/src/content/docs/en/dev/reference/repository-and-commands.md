---
title: Repository and development commands
description: Reference for the main LeonAid directories, toolchains, and wrapper commands.
docId: DOC-P036
audience: [dev]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

| Path                                  | Contents                                                  |
| ------------------------------------- | --------------------------------------------------------- |
| `src/leonaid/domain`                  | domain models and rules without transport details         |
| `src/leonaid/adapters`                | PostgreSQL, Twenty, storage, and other adapters           |
| `src/leonaid/entrypoints`             | FastAPI and worker entry points                           |
| `apps/web`, `apps/pwa`, `apps/public` | admin, acquisition, and public UIs                        |
| `apps/campaign-site`                  | Astro/EmDash campaign rendering                           |
| `apps/docs`                           | this Starlight site and its quality gates                 |
| `packages/api-client`                 | canonical OpenAPI and generated TypeScript client         |
| `packages/features`, `packages/ui`    | shared feature and UI components                          |
| `migrations`                          | Alembic revision graph for Core                           |
| `infra`                               | Compose, pilot, locks, backup, upgrade, and Twenty schema |
| `tools` / `tests`                     | executable contracts, generators, and fixtures            |

`./leonaid bootstrap`, `doctor`, `dev`, and `check` form the general development
flow. `generate-api-client` updates API artifacts. `docs-dev`, `docs-check`,
`docs-build`, and `docs-preview` operate the documentation. Feature slices use
their matching `test-…` commands. `./leonaid help` is the current complete
command reference.
