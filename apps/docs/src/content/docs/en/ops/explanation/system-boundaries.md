---
title: System and persistence boundaries
description: Why LeonAid Core, Twenty, RustFS, and the user interfaces have separate responsibilities.
docId: DOC-P028
audience: [ops]
diataxis: explanation
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 6d3891e2a7f6497307f1cd2927bb6efe1b4b97aa
reviewer: Björn Schotte
---

LeonAid Core owns identities, campaign memberships, charity actions,
assignments, activities, orders, invoices, payments, audit, and outbox. Twenty
owns companies and people. Core references stable Twenty IDs and stores
snapshots when later CRM changes must not rewrite history.

RustFS stores document bytes only; Core keeps the object key, version, SHA-256,
size, and domain reference. Invoice number, invoice snapshot, and outbox event
are created in one Core transaction. Rendering and delivery follow as
idempotent jobs. Browsers and Astro Actions hold no authoritative domain logic.

These boundaries define a recovery point: both PostgreSQL databases, Twenty
files, and RustFS must be captured together. The Valkey queue store
(`twenty-redis`) can be rebuilt. One
installation represents exactly one club or operating organisation; further
organisations are isolated through separate installations.
