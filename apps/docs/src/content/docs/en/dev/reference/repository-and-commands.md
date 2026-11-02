---
title: Repository and development commands
description: Reference for the main LeonAid directories, toolchains, and wrapper commands.
docId: DOC-P036
audience: [dev]
diataxis: reference
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: b157297a8877c2f88787adcc0339b42363342faa
reviewer: Björn Schotte
---

| Path                                  | Contents                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------- |
| `src/leonaid/domain`                  | domain models and rules without transport details                         |
| `src/leonaid/adapters`                | PostgreSQL, Twenty, storage, and other adapters                           |
| `src/leonaid/entrypoints`             | FastAPI and worker entry points                                           |
| `src/leonaid/platform`                | shared technical contracts (navigation, HTTP envelope, worker loops)      |
| `src/leonaid/modules`                 | business modules; each owns its domain, application, adapters, and routes |
| `src/leonaid/bootstrap`               | static module registration for API and worker                             |
| `apps/web`, `apps/pwa`, `apps/public` | admin, acquisition, and public UIs                                        |
| `apps/campaign-site`                  | Astro/EmDash campaign rendering                                           |
| `apps/docs`                           | this Starlight site and its quality gates                                 |
| `packages/api-client`                 | canonical OpenAPI and generated TypeScript client                         |
| `packages/features`, `packages/ui`    | shared feature and UI components                                          |
| `migrations`                          | Alembic revision graph for Core                                           |
| `infra`                               | Compose, pilot, locks, backup, upgrade, and Twenty schema                 |
| `tools` / `tests`                     | executable contracts, generators, and fixtures                            |

Modules are registered explicitly in `src/leonaid/bootstrap/api.py` (routes,
navigation) and `src/leonaid/bootstrap/worker.py` (outbox handlers, background
loops). Startup fails on duplicate module IDs, missing or cyclic module
dependencies, colliding routes, duplicate handlers, and duplicate loops. Web
pages of a module register in the web shell as a `UiModule`
(`packages/features/src/modules.ts`). `tests/unit/test_architecture_boundaries.py`
enforces the import direction `entrypoints → bootstrap → modules → platform`.
Other modules use a module only through its `api.py`, for example
`leonaid.modules.surveys.api.SurveyService`.

`./leonaid bootstrap`, `doctor`, `dev`, and `check` form the general development
flow. `generate-api-client` updates API artifacts. `docs-dev`, `docs-check`,
`docs-build`, and `docs-preview` operate the documentation. Feature slices use
their matching `test-…` commands. `./leonaid help` is the current complete
command reference.
