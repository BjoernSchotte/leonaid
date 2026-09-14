---
title: Make your first verified change
description: Prepare a fresh checkout, make a small change, and prove it with the relevant contract.
docId: DOC-P031
audience: [dev]
diataxis: tutorial
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

You need Git, Docker with Compose v2, and at least 5 GiB of free space.

1. Clone LeonAid into a fresh checkout and create a working branch.
2. Run `./leonaid bootstrap`, followed by `./leonaid doctor`.
3. Read `PERSONAS.md`, the affected domain or UI implementation, and the
   nearest executable test. Use specs and ADRs as context.
4. Make one coherent change. If it affects the API, configuration, user flow,
   or operations, update the relevant docs at the same code revision.
5. Run the narrowest relevant `./leonaid test-…` command first. For a docs-only
   change, run `./leonaid docs-check` and `docs-build`.
6. Before handoff, run `./leonaid check` from a clean working tree.
7. Inspect the diff, generated files, secrets, and unexpected changes.

`./leonaid test-handoff` repeats this setup in a fresh checkout and proves that
the documented prerequisites are complete. One targeted green test does not
replace the full gate required for the actual change.
