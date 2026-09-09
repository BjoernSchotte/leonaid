# EmDash local spike — acceptance record

Status: **IN PROGRESS — no GO_LOCAL or production approval yet.**

Acceptance scope: Phase A of [PLAN.md](PLAN.md), explicitly approved on
2026-09-09. Phase B remains an open production-readiness follow-up. This report
does not turn historical partial checkpoints into completed acceptance gates.

## Source and runtime identity

- Source inspected for this record: LeonAid
  `c2b4459a64ceabd35eac7ccfab6850b3b5ae262d`.
- Pinned upstream: EmDash 0.36.0, source
  `603062902369d9695608e85c2d034d4f66f7a1f1`.
- Visible local project: `leonaid-emdash-d388-visible`.
- HTTPS origin: `https://localhost:19443`; diagnostic HTTP: loopback port 19480.
  Docker inspection confirmed only the proxy publishes these loopback ports;
  Core, CMS, databases and storage publish no host ports. All fourteen running
  project services reported healthy during this check.
- Actual running image IDs, inspected directly rather than inferred from tags:
  - CMS: `sha256:0e4306fdf9ab395265bc543785ea1ba2014fb25faa4978140f6ad358f25f3876`
  - Web after the navigation fix: `sha256:62c419ff38d94f2f271db9017de1366ef51c80e1007ee1fb00443f42dbcd8671`
  - Core: `sha256:b898b8372881141ad5edb49058f8e1b1f0f9e83f6595b2467198ba9bbc67fae6`
  - Existing public frontend: `sha256:6bc97cf60e97aec34aa8a3656acef94da813a1e39bac2579e77870b174d5dc98`

These are local runtime identities, not published release digests or proof of
pilot image promotion.

## Current visible and HTTP observations

Verified on 2026-09-09 in the In-App Browser:

1. The scoped CMS list contains the existing Krapfentaxi page, marked
   `Published Pending changes`, with its canonical public link.
2. **Zurück zu LeonAid** opens `/admin/` in the same tab and retains the
   existing Charity Admin login.
3. The dashboard's **Microsite bearbeiten** link for Krapfentaxi 2026 resolves
   to its exact existing CMS editor, without another login. The editor's
   immutable Core action field matches the selected campaign; Save is disabled
   with the `Saved` label on initial arrival.
4. Browser Back from that unchanged editor returns to the dashboard with
   Krapfentaxi 2026 selected. No content was saved, published or discarded.
5. The public canonical page renders the campaign, original media, Core
   offering and order form. Its separate tab shares the browser session; this
   observation alone is not anonymous-access proof.
6. Switching the dashboard selector to Krapfentaxi 2025 updates the URL,
   dashboard data and contextual editor link to that campaign. The initial
   check reproduced a stale shell label and generic sidebar editor link:
   `replaceState` in the child did not notify the parent shell. The fix uses
   one shared URL-selection hook across dashboard, acquisition, orders and
   invoices, and one shared campaign-specific link authorization function.
   After updating only the visible Web container, switching 2025 → 2026 without
   reloading updated both the page and shell. The mobile drawer's editor link
   targeted the selected 2026 action and opened its exact existing CMS editor
   in the same tab with the retained Charity Admin login. No editorial or
   operational data was changed. This confirms the reproduced dashboard defect;
   it is not a claim that every shell-navigation permutation was retested.

Navigation checks passed in the pinned Node container:

```sh
node node_modules/typescript/bin/tsc --noEmit -p apps/web/tsconfig.json
# Working directory: apps/web
node ../../node_modules/vitest/vitest.mjs run --config vitest.config.ts src/action-location.test.tsx src/campaign-editor-link.test.tsx
```

Both test files passed (three tests), covering initial/changed selection,
subscriber updates, history/state/hash preservation and action-specific link
authorization. The isolated project's `docker compose ... build web` succeeded;
only its `web` service was recreated with `--no-deps --no-build --wait`.
Existing source-map/chunk-size build warnings remain. No new dependency or
second router was introduced.

Independent requests using the project's trusted CA, no cookies and no skipped
certificate verification confirmed:

- `GET /campaigns/krapfentaxi-2026/` → 200.
- `POST /api/v1/public/actions/krapfentaxi-2026/orders` without a body → 404.
  This is a current ingress smoke check, not a substitute for the existing
  valid-payload ingress-denial and actual order-persistence tests.

The existing pending editorial draft remains untouched. The final coherent
edit/publish/order journey must first account for that draft rather than
silently publishing unrelated pending changes.

## Evidence consolidation and remaining closure

- [ ] Close Phase A ordinary-use navigation gaps and consolidate the existing
      keyboard, mobile and unsaved-change evidence. The observations above do
      not prove all navigation paths.
- [ ] Complete the coherent visible edit → publish → anonymous view → order
      journey and independently verify Core/Twenty persistence.
- [ ] Audit current authorization, draft/media isolation, aliases, bootstrap,
      session lifecycle and internal order transport against the plan's
      mandatory security matrix. Historical detailed command results remain
      in PLAN.md; an unchecked parent requirement is not automatically proven.
- [ ] Complete current local encrypted recovery verification, including
      migrated content/media and preservation of newer Core orders.
      `./leonaid test-emdash-spike --case cutover-rollback` has been started
      against the source revision above; its result is pending. Its source
      project is `leonaid-poc112-tmp-cde72ryn28`, with fresh restore target
      `leonaid-restore-tmp-cde72ryn28`. It uses fresh,
      uniquely named projects, isolated subnets and no host ports, not the
      persistent visible demo or another worktree's resources.
- [ ] Record final repository quality checks, applicable regression commands,
      patch maintenance burden, limitations and explicit local outcome.

Production runtime-origin/pilot activation, complete release/doctor/monitoring
integration and successor-version upgrade rehearsal remain Phase B, as listed
in PLAN.md. No production service has been activated by this acceptance work.
