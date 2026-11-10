---
title: Roles and access scopes
description: Reference for the implemented global and campaign-scoped LeonAid roles.
docId: DOC-P016
audience: [user]
diataxis: reference
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: ee007bf6c2e21edf0b939ee5641b3a9f98674560
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

| Role              | Scope                             | Current permissions                                                         |
| ----------------- | --------------------------------- | --------------------------------------------------------------------------- |
| `system_admin`    | global                            | manage users, global roles, integrations, privacy, and operations functions |
| `finance_reader`  | global or campaign                | read invoices, PDFs, delivery, payments, and open amounts                   |
| `finance_manager` | global                            | record and reverse payments, cancel invoices in a controlled way            |
| `charity_admin`   | one campaign                      | manage that campaign, members, orders, invoices, and finance actions. With flag `delivery.tours`: **Touren planen** (plan tours) |
| `acquirer`        | one campaign                      | work with assigned sponsors, activities, and orders                         |
| `driver` (UI: **Ausfahrer**) | campaign with delivery capability | in the app's **Auslieferung**, see only their own assigned deliveries with address and contact, without amounts, and tick them off while the window is open. With flag `delivery.tours`: **Meine Tour** (tab **Tour**) |

One person can hold several roles. Campaign roles apply only to the named
charity campaign. A charity administrator gains neither access to other
campaigns nor a global role. An acquirer cannot see invoices. The interface
hides unavailable actions and the server enforces the same boundaries on every
request.

Only a system administrator grants global roles. A charity administrator may
change campaign roles only in campaigns they manage. Changes apply from the
next request; sensitive administration actions require a freshly confirmed
login.

## Start area after sign-in

After sign-in, LeonAid opens the area that fits your roles. With its own admin
host (`app.<domain>`) this also applies when you only type the address:

| Roles                                     | Start area                         |
| ----------------------------------------- | ---------------------------------- |
| an acquisition role (also next to others) | acquisition app                    |
| `system_admin`                            | administration, page **System**    |
| `charity_admin`                           | administration, overview. With flag `delivery.tours`: **Touren planen** (plan tours) |
| finance roles                             | administration, **Rechnungen**     |
| driver only, or no administration role    | acquisition app                    |

With roles for both areas, switch with **Akquise-App** in the administration
rail or with **Zur Verwaltung** under **Mehr** in the app. In the
administration's command palette choose **Verwaltung als Startbereich
verwenden**; in the app, under **Mehr**, **Akquise-App als Startbereich
verwenden**. LeonAid keeps the choice while you hold a role for that area.
After a choice, both places also offer **Standard-Startbereich verwenden**:
it drops the choice, and the table above applies again. A link to a specific
page brings you exactly there after sign-in.

