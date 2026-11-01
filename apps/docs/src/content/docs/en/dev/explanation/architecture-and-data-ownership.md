---
title: Architecture and data ownership
description: The Core, CRM, storage, and frontend boundaries behind LeonAid's modular architecture.
docId: DOC-P037
audience: [dev]
diataxis: explanation
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
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
command backfills records created outside LeonAid. RustFS holds private
document bytes; metadata and domain links
remain in Core. Rendering and delivery process transactionally created outbox
events idempotently.

Web, PWA, Public, and Campaign Site call the generated `@leonaid/api-client`.
They may coordinate rendering and input but cannot own authoritative pricing,
permission, or status logic. Caddy is the only exposed runtime entry point.
One installation belongs to one club or operating organisation; multiple
organisations are isolated through separate installations.
