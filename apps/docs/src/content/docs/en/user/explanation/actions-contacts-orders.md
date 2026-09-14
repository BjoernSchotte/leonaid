---
title: Campaigns, contacts, and orders
description: How LeonAid connects campaigns, CRM parties, responsibilities, and binding orders.
docId: DOC-P018
audience: [user]
diataxis: explanation
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

A **charity campaign** defines its period, purpose, offerings, goal,
publication, and roles. It is the boundary within which LeonAid authorizes
responsibilities and financial transactions.

A company or person is a **CRM party** in Twenty. LeonAid Core stores the
campaign-specific acquisition assignment: who is responsible and which status,
reminder, and activities belong to the campaign. Several acquirers can share a
party without duplicating the CRM record.

An **order** is a `Commitment` in Core. It stores the source, server-valued
lines, an invoice recipient, and, where applicable, delivery address, contact,
and booked delivery window. Public forms can create or reuse a CRM party, while
the binding order remains a Core record.

Issuing an invoice creates an immutable snapshot of recipient, issuer, lines,
prices, payment details, and legal text. Later changes to the CRM contact or a
delivery window do not rewrite the historic document. This separation
preserves traceability and explains why corrections use a separate transaction.
