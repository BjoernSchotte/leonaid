# Porting the modular platform (draft PR #7) to main

Status: 2026-11-02. Source: draft PR #7 (`origin/codex/modular-platform-spec`, base `de0391c`, September 2026) plus `origin/wip/modular-platform-spec-task-structure` (#7 + one WIP commit: task priority, tags, checklists). Main had moved about 171 commits ahead by then. The diff is 295 files and +50,579/−4,861 lines; about 17,000 of those lines are the regenerated `openapi.json`.

The #7 branch is not merged. Each step below re-implements one slice on current main. Code from #7 is ported where it fits and adapted to main's conventions. Old infrastructure from #7 is not carried over. The #7 specs (`specs/modular-platform/{PLAN,PROGRESS,AUDIT,ROLLBACK}.md`, `specs/knowledge-editor/`, `specs/tasks-ux/`) stay on the #7 branch as history. This file is the plan for the port.

## 1. What #7 contains

| Area               | #7 contents                                                                                                                                                                                                                                                                                                                                                                                  | Lines (approx.)      |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| Bootstrap/registry | `bootstrap/{registry,api,worker}.py`, `platform/{navigation,http,http_body,worker_signals}.py`, `navigation_for(module_items)`, recursive architecture tests, `tests/unit/test_module_registration.py`                                                                                                                                                                                       | 900                  |
| Frontend registry  | `packages/features/src/{modules,registered-modules,pwa-modules}.ts`, shell routing from module routes in `apps/web` / `apps/pwa`, `module-registration.test.ts`                                                                                                                                                                                                                              | 400                  |
| Surveys module     | Survey domain/application/adapters/Typst template moved to `modules/surveys/`, typed facade `modules/surveys/api.py` and `models.py`, `routes.py` (was `entrypoints/fastapi/surveys.py`), `jobs.py` (handlers + deadline sweep), web UI moved to `packages/features/src/surveys/`, PWA link                                                                                                  | 2,500 (mostly moves) |
| Outbox/jobs        | Optional `available_at` on `PendingOutboxEvent`; per-handler timeouts; job duration in logs; no raw exception text in `last_error_detail`; `OutboxWorker.close()`; `complete_resolved_event`; operations show next attempt and oldest due age; worker activity timestamps                                                                                                                    | 600                  |
| Tasks              | Migrations 0037/0042/0043/0044 (lists, members, epics, tasks, personal plans, manual order, tags, checklists, priority); `modules/tasks/{api,repository,routes,ordering,planning}.py`; UI `packages/features/src/tasks/*` (dnd-kit); shared `access-members`, `action-contexts`, `module-search`; contracts `tools/tasks/*`; e2e `modules-tasks`, `tasks-*`                                  | 11,000               |
| Materials          | Migration 0040 (material, versions, members, plus `knowledge_page_material`); `modules/materials/*`; S3 upload/download, cleanup CLI; UI `materials/*`, picker; contracts `tools/materials/*`; e2e                                                                                                                                                                                           | 5,500                |
| Knowledge          | Migrations 0038/0039; `modules/knowledge/{api,document,repository,routes}.py` (bounded Tiptap document contract); Tiptap editor UI; "task from page"; contracts `tools/knowledge/*`; e2e `knowledge-editor`, `modules-knowledge`                                                                                                                                                             | 5,500                |
| Inbox              | Migration 0041 (`inbox_case` with `contact_job_id → outbox_event`, comments, task/material refs); `modules/inbox/{api,jobs,repository,routes}.py`; Twenty contact-link job with create intent, correlation, `needs_review`, manual resolution; public form `apps/public/src/components/PublicInbox.astro` + campaign-site; UI `inbox/*`; contracts `tools/inbox/*`; e2e `public-inbox-retry` | 7,500                |
| Test/CI glue       | `tools/testing/{modular_browser.sh,spa_routes.mjs,shared_stack.py,local_stack.py}`, `tools/schema/code_rollback.py`, CI workflow entries, static-server SPA fallback for module deep links                                                                                                                                                                                                   | 1,500                |

Module dependencies (imports and foreign keys):

```text
knowledge -> tasks, materials
inbox     -> tasks, materials, outbox (complete_resolved_event, handler timeouts)
materials -> (platform only)
tasks     -> (platform only)
surveys   -> (platform only)
```

## 2. What changed on main since #7's base

| Main change                                                                                                                    | Effect on the port                                                                                                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Worker loop health (`LoopHealth`, `entrypoints/worker/health.py`), readiness from all loops                                    | Use main's model. #7's `worker_signals.py` is not ported. A background-task contribution carries its own `LoopHealth`.                                                                                                                    |
| Outbox retention loop (migrations 0039/0040 on main, `entrypoints/worker/retention.py`) deletes old completed/dead-letter rows | #7's `inbox_case.contact_job_id NOT NULL REFERENCES outbox_event(id)` would block retention. Inbox must use `ON DELETE SET NULL` like `0040_mail_delivery_set_null`, and it must keep its contact status on the case, not on the job row. |
| Migrations on main end at `0040_mail_delivery_set_null`                                                                        | #7's 0037–0044 are renumbered from 0041. port-pr3 needs no migration (agreed). Each #7 module's migrations collapse into one migration per PR, because they were never released.                                                          |
| Strict CSP (`style-src 'self'`, no `unsafe-inline`; Astro CSP hashes)                                                          | The Tiptap `TextAlign` extension renders `style="text-align:…"`, which strict CSP blocks. Render alignment as classes. The public inbox form must work without inline script/style. Browser e2e must assert there are no CSP violations.  |
| Non-root, read-only containers                                                                                                 | Material upload streaming must use no temp files outside the allowed tmpfs. The surveys erasure archive dir keeps working.                                                                                                                |
| Twenty 2.54, admin-only CRM, Valkey                                                                                            | Inbox contact linking uses the existing `TwentyCrmGateway` via the integration key. Re-check the people API against 2.54 in the inbox step.                                                                                               |
| Capability-driven campaigns                                                                                                    | Inbox availability on public action pages follows capabilities, not the old order-form flag logic from #7.                                                                                                                                |
| Security gates (Trivy/OSV HIGH, waivers), Renovate                                                                             | New npm deps (Tiptap 3, dnd-kit) need current versions without HIGH advisories at port time.                                                                                                                                              |
| English code, comments and CLI (PR #43)                                                                                        | Code, comments, test names and developer errors from #7 are translated. UI and API user-facing messages stay German.                                                                                                                      |
| Teardown guard (`tools/testing/owned_teardown.sh`), slot runner                                                                | The new real-system suites use the existing runners and teardown guard. #7's `shared_stack.py` changes are re-checked against main before porting.                                                                                        |
| Memory budget check (PR #44): sum of core `mem_limit` ≤ 6208 MiB, 136 MiB free                                                 | No new services. Any raise of the api/worker limits must fit into the budget and be reported to memory-remeasure.                                                                                                                         |

## 3. PR sequence

Each step is one PR on branch `feat/modular-<step>`. It is merged before the next one starts. Every PR has English code, unit tests, the relevant real-system suites, browser e2e for UI, docs, a green `./leonaid check` and green CI.

1. **bootstrap** — `bootstrap/registry.py` with startup validation: module IDs, dependencies and cycles, route collisions (core router included), duplicate outbox handlers and background loops. `bootstrap/api.py` holds the API module list, navigation contributions and survey service construction. `bootstrap/worker.py` holds `build_worker`, the handlers grouped per owning area and the background loops. `platform/` gets `navigation.py`, `http.py` (`TransportModel`, error envelope) and `background.py` (the loop contract; health stays in the worker shell). The surveys entry points move to `modules/surveys/`: `routes.py` (was `entrypoints/fastapi/surveys.py`), `jobs.py` (handlers and deadline sweep) and `navigation.py`. `navigation_for` takes module items. The frontend gets a `UiModule` registry in `packages/features`, and the web shell resolves surveys through it. Architecture tests become recursive for `platform/`, `modules/` and `bootstrap/`. No behavior change: routes, OpenAPI, navigation JSON, worker handlers, loop names and readiness stay the same. This plan is committed with this PR.
2. **surveys** — move the survey domain, application and adapters (Postgres, mail, storage, Typst template) to `modules/surveys/`, and the survey web UI to `packages/features/src/surveys/`. Add the typed public facade (`modules/surveys/api.py`, request models in `models.py`); HTTP routes call the same typed methods as direct Python callers, and the repository checks current database permissions for both. Old paths are removed, not re-exported. URLs, payloads, handler names and stored jobs stay compatible. Survey, upgrade, backup and recovery suites cover the moved code.
3. **outbox** — optional timezone-aware `available_at` on `PendingOutboxEvent`; per-handler timeouts below the lease (survey export 240 s); safe error details (codes only); job duration in logs; `OutboxWorker.close()`; `complete_resolved_event`; next attempt and oldest due age in operations. This is checked against the retention loop and its indexes. No migration. Before inbox, this step can merge into step 7 if review shows it is too small on its own.
4. **tasks** — includes the WIP commit (priority, tags, checklists). One migration `0041_tasks`. Shared UI (`access-members`, `action-contexts`, `module-search`) and the `@dnd-kit` dependencies arrive here. Static-server/SPA deep-link fallback for module routes. The PWA shell gets module registration and module navigation keys here, including the PWA link to the web survey editor (moved from step 2, because the PWA tab bar changes with the first PWA module anyway).
5. **materials** — migration `0042_materials` (without `knowledge_page_material`, which moves to step 6); generic request-body limit `platform/http_body.py` (replaces the survey-only middleware; uploads need a larger limit); S3 streaming upload/download within the read-only container rules; cleanup CLI via `./leonaid`; picker UI.
6. **knowledge** — migration `0043_knowledge` (pages, revisions, members, task refs, material refs, access revision); Tiptap editor adapted to strict CSP; "task from page". It depends on tasks and materials.
7. **inbox** — migration `0044_inbox` (`contact_job_id` nullable with `ON DELETE SET NULL`, status owned by the case); contact-link job with Twenty 2.54; manual resolution; public form on `apps/public` and campaign-site under strict CSP; web/PWA case UI.

After step 7: close #7 with a comment that lists the PRs that replaced it. Branches are kept.

Order change compared with the default: materials come before knowledge, because knowledge revisions reference material versions.

## 4. Migrations

| Step | Revision         | down_revision                                             | Content                                             |
| ---- | ---------------- | --------------------------------------------------------- | --------------------------------------------------- |
| 4    | `0041_tasks`     | `0040_mail_delivery_set_null` (or the head at merge time) | #7 0037 + 0042 + 0043 + 0044                        |
| 5    | `0042_materials` | `0041_tasks`                                              | #7 0040 without `knowledge_page_material`           |
| 6    | `0043_knowledge` | `0042_materials`                                          | #7 0038 + 0039 + `knowledge_page_material`          |
| 7    | `0044_inbox`     | `0043_knowledge`                                          | #7 0041 with the retention-compatible job reference |

If another PR adds a migration first, the next module PR takes the following number and rebases its `down_revision` on the current head. Every migration is additive and has a tested downgrade. New tables are covered by `tools/schema` smoke, backup/restore inventory and upgrade suites.

## 5. Memory (8 GB VPS)

- No new containers. API (384m) and worker (512m) gain imported modules: about 10–30 MiB RSS expected for all four modules together. This is measured per step with the existing measurement tools and reported to memory-remeasure. A limit raise only happens if a measurement requires it, and it must fit the 6208 MiB core budget (136 MiB free after PR #44).
- Material uploads (≤ 25 MiB) are streamed to object storage in bounded chunks, never fully buffered. Peak memory per upload must stay under about 2× the chunk size.
- Web/PWA bundles grow (Tiptap, dnd-kit). Module pages are lazy-loaded. Static servers (64m) are not affected, because the content is static.
- The worker gains one handler (inbox contact link) and no new loops. The existing serial processing stays.

## 6. Risks

- **Size**: steps 4–7 are about 30k lines of logic, UI and contracts. Each needs full real-system and browser runs, and these are slot-limited (at most 3 stacks per host). Expect one to two working days per module step.
- **CSP**: Tiptap/ProseMirror inline styles and any React `style` attributes rendered to HTML. Mitigation: class-based alignment, plus a CSP violation listener in e2e.
- **Retention vs. foreign keys to `outbox_event`**: covered in step 7. The same check applies to any new table that references `outbox_event`.
- **OpenAPI/generated client conflicts** with parallel PRs (port-pr3 and others): regenerate after every main merge, never merge-edit by hand.
- **Twenty 2.54 people API drift** for inbox correlation: re-verify against the pinned image in the inbox step.
- **Dependency advisories** for new npm packages: they block on the HIGH gate.

## 7. Open product questions (for the user before the step starts)

- Step 4: keep the full tasks UX from #7, including personal planning, manual ordering, priority, tags and checklists, or ship a smaller first cut?
- Step 7: the public inbox forms create CRM people from anonymous submissions. Confirm that this stays wanted, and confirm the privacy wording on the public form.
- Steps 4–7: modules are visible to every active account (as in #7, with no per-club activation). Confirm that no per-install module switch is needed.
