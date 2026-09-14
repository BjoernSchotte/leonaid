---
title: Update the API contract
description: Change FastAPI, canonical OpenAPI, and the TypeScript client together in one reproducible flow.
docId: DOC-P032
audience: [dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

1. Change the route and models in FastAPI Core together with a relevant domain
   or contract test.
2. Run `./leonaid generate-api-client`. Do not hand-edit
   `packages/api-client/openapi.json` or `packages/api-client/src/generated.ts`.
3. Inspect both generated diffs. Field names, required properties, status
   codes, security, and error shapes must match the intended Core change.
4. Update consumers and curated DE/EN explanations. The docs API reference is
   generated from exactly this JSON during every docs gate.
5. Run `tools/openapi/test.sh` and the affected feature test. The OpenAPI test
   regenerates and compares both files byte for byte, typechecks them, and
   exercises the real API client.

A breaking change requires an exact, reasoned entry in the versioned breaking
approval contract. A missing contract or one that differs from Core blocks the
contract test and docs reference.
