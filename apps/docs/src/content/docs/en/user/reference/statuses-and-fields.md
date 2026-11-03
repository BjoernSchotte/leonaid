---
title: Statuses and important fields
description: Reference for campaign, acquisition, order, invoice, and delivery statuses.
docId: DOC-P017
audience: [user]
diataxis: reference
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 1c054b0fb55c59b9f884aee956b431a519ce521d
reviewer: Björn Schotte
---

## Charity campaign

`draft` (**Entwurf**) → `scheduled` (**Geplant**) → `active` (**Aktiv**) →
`completed` (**Abgeschlossen**) → `archived` (**Archiviert**). A scheduled
campaign can return to draft. Completed campaigns can only be archived;
archived campaigns are read-only.

## Acquisition

| Technical     | Interface   | Meaning                                        |
| ------------- | ----------- | ---------------------------------------------- |
| `open`        | Offen       | work has not started                           |
| `contacted`   | Kontaktiert | a contact attempt is recorded                  |
| `committed`   | Zugesagt    | the sponsor committed or ordered               |
| `declined`    | Abgesagt    | no further acquisition step is planned         |
| `handed_over` | Übergeben   | internal handoff status, not normally editable |

Reminder, priority, and next action belong to the assignment, not to the CRM
contact itself.

## Order

`draft` (**Entwurf**), `review_ready` (**Prüfbereit**), `confirmed`
(**Bestätigt**), `invoiced` (**Fakturiert**), and `cancelled` (**Storniert**).
The source is `acquisition`, `public_form`, or `admin`. Prices, lines, invoice
recipient, and delivery details are checked on the server; a booked delivery
window is retained as a snapshot.

## Invoice and delivery

Invoices are `issued` (**Ausgestellt**), `sent` (**Versendet**), `paid`
(**Bezahlt**), or `cancelled` (**Storniert**). The invoice list shows issued
or sent invoices with a remaining amount as **Offen**, and as **Überfällig**
after their due date. The status cannot be edited in the list; payment and
cancellation are explicit commands in the detail pane.

Email delivery has separate statuses: `queued`, `sending`, `retrying`,
`failed`, and `sent`. A delivery failure does not change the invoice. The PDF
is independently `pending`, `available`, or `deleted`.
