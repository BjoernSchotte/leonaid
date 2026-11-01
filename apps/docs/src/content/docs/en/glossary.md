---
title: Glossary
description: The canonical English LeonAid terms and their German equivalents.
docId: DOC-P002
audience: [user, ops, dev]
diataxis: reference
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 3ffbc7ebf669d360fb6ec7352034e4067d7eb8a4
reviewer: Björn Schotte
---

| English               | Deutsch              | Meaning in the product                                                                                            |
| --------------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------- |
| charity campaign      | Charity-Aktion       | The domain boundary for roles, offerings, orders, invoices, and public presentation.                              |
| charity administrator | Charity-Admin        | A campaign-scoped role that manages only its assigned campaign.                                                   |
| acquirer              | Akquisiteur          | A campaign-scoped role for assigned companies and contacts.                                                       |
| sponsor               | Sponsor              | A company or person in the CRM that can be assigned to acquisition work.                                          |
| order                 | Bestellung           | A binding selection of offerings with a server-calculated price. The code calls the domain object `Commitment`.   |
| delivery window       | Lieferfenster        | A delivery period released by a charity administrator for a campaign with delivery.                               |
| invoice               | Rechnung             | An immutable document snapshot with its own status and PDF.                                                       |
| system administrator  | System-Admin         | The global product role for users and system-wide settings.                                                       |
| system operator       | Sysadmin / Betreiber | The person operating hosts, containers, secrets, backups, and recovery. This is not automatically a product role. |
| LeonAid Core          | LeonAid Core         | The authoritative application for domain state, permissions, and transactions.                                    |
