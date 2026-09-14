---
title: Roles and access scopes
description: Reference for the implemented global and campaign-scoped LeonAid roles.
docId: DOC-P016
audience: [user]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

| Role              | Scope                             | Current permissions                                                         |
| ----------------- | --------------------------------- | --------------------------------------------------------------------------- |
| `system_admin`    | global                            | manage users, global roles, integrations, privacy, and operations functions |
| `finance_reader`  | global or campaign                | read invoices, PDFs, delivery, payments, and open amounts                   |
| `finance_manager` | global                            | record full payments and cancel invoices in a controlled way                |
| `charity_admin`   | one campaign                      | manage that campaign, members, orders, invoices, and finance actions        |
| `acquirer`        | one campaign                      | work with assigned sponsors, activities, and orders                         |
| `driver`          | campaign with delivery capability | role is modelled; the production driver and routing workflow is deferred    |

One person can hold several roles. Campaign roles apply only to the named
charity campaign. A charity administrator gains neither access to other
campaigns nor a global role. An acquirer cannot see invoices. The interface
hides unavailable actions and the server enforces the same boundaries on every
request.

Only a system administrator grants global roles. A charity administrator may
change campaign roles only in campaigns they manage. Changes apply from the
next request; sensitive administration actions require a freshly confirmed
login.
