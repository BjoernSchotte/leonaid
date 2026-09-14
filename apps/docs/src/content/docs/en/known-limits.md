---
title: Known limits
description: Verified limits of the current LeonAid development and pilot state.
docId: DOC-P003
audience: [user, ops, dev]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

This documentation describes the current development state. It is not a
general production approval.

- The product interface and its outbound messages are currently in German.
  English guides quote German UI labels verbatim.
- One installation represents one club or isolated tenant. Shared
  multi-tenancy is not supported.
- The driver workflow is deferred. Delivery addresses and delivery windows are
  stored, but a driver app with routes and delivery status is outside the
  current scope.
- `finance_reader` can only read documents. The maintained demo user Finn
  Finanzen proves this read-only access. Full payment and cancellation require
  `finance_manager` or the charity administrator for the affected campaign.
- Members cannot change their own login email. A system administrator starts
  the change and the new address must confirm it.
- Public orders require a published campaign with an active order form and an
  available offering. When delivery planning is enabled, an available delivery
  window is also required.
- An issued invoice and its PDF are never overwritten. Corrections use a
  cancellation and a new transaction.
- Partial payments and overpayments are not implemented; recording a payment
  accepts only the exact full invoice amount.
- The separate documentation site does not yet have an approved domain. Until
  DOC-070, the versioned source and CI artifacts are the reliable entry points.

Report a discrepancy with the affected product route, visible message, and
commit. The implementation remains the source of truth.
