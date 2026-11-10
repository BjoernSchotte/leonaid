---
title: Architecture and data ownership
description: The Core, CRM, storage, and frontend boundaries behind LeonAid's modular architecture.
docId: DOC-P037
audience: [dev]
diataxis: explanation
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: e2e199217b9b0d23fc0ad225051cfc36fe01daf5
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

FastAPI Core owns authentication, authorisation, and every domain operation.
Its PostgreSQL database stores identities, actions, memberships, assignments,
activities, orders, invoices, payments, audit, and outbox. Core evaluates
policies on every request.

Twenty is the system of record for companies and people. LeonAid stores stable
CRM IDs and immutable domain snapshots rather than a second authoritative
contact copy. Request paths query Twenty only by name, match key, or
explicit record IDs, never by listing a whole collection: Core stores a
normalized match key in a provisioned field on every company and person it
writes, finds duplicates with an exact key lookup, and an idempotent repair
command backfills records created outside LeonAid. The one exception to "no
contact copy" is the search index `sponsor_search_entry`: it holds the name
and the city of the companies and people that have an acquisition assignment,
so the search finds sponsors without a CRM call per keystroke; a worker keeps
it in step with Twenty. RustFS holds private
document bytes; metadata and domain links
remain in Core. Rendering and delivery process transactionally created outbox
events idempotently.

Web, PWA, Public, and Campaign Site call the generated `@leonaid/api-client`.
They may coordinate rendering and input but cannot own authoritative pricing,
permission, or status logic. Caddy is the only exposed runtime entry point.
One installation belongs to one club or operating organisation; multiple
organisations are isolated through separate installations.
