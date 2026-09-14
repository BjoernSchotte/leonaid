---
title: Debug a local failure
description: Trace a reproducible LeonAid failure from the wrapper to the service that owns the behavior.
docId: DOC-P033
audience: [dev]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

1. Run `./leonaid doctor` and first resolve missing locks, secrets, packages, or
   an unavailable Docker daemon.
2. Reproduce the fault with the smallest suitable `./leonaid test-…` command.
   Test artifacts stay ignored under `.artifacts/`.
3. Inspect `docker compose --env-file .env.local -f infra/compose/compose.yml
ps`, followed by logs for the affected service only.
4. Follow ownership: HTTP, policies, and domain data belong to FastAPI Core;
   companies and people to Twenty; document bytes to RustFS; asynchronous
   delivery to outbox and worker; rendering to the relevant web app.
5. Use a technical correlation ID. Do not copy payloads, tokens, email
   addresses, or document bytes into issues or logs.
6. Add a reproducing test, fix the cause, then run the targeted test followed by
   all required wider gates.

The VS Code debug profiles attach to Compose services rather than starting a
second application, so configuration and data paths match integration tests.
