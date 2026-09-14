---
title: Permissions within a campaign
description: Why LeonAid binds navigation, records, and actions to global and campaign-scoped roles.
docId: DOC-P019
audience: [user]
diataxis: explanation
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

LeonAid separates global responsibility from work in one charity campaign.
`system_admin`, `finance_reader`, and `finance_manager` may act globally.
`charity_admin`, `acquirer`, campaign-scoped `finance_reader`, and `driver`
always belong to one campaign.

The same person can therefore be a charity administrator in campaign A, an
acquirer in campaign B, and have no access to campaign C. Navigation is derived
from the current identity. A hidden control is only the visible result; Core
also enforces the boundary for direct API requests.

Data visibility may be narrower than the campaign role. Within a campaign, an
acquirer sees only assigned CRM parties. Assignment grants neither finance nor
administration access. Historic activities, orders, and documents remain after
a role is removed, while new requests immediately respect the revoked access.

Sensitive actions such as changing roles or issuing an invoice require fresh
confirmation of the current session. This limits the impact of an unattended
signed-in device without requiring a new login for routine work.
