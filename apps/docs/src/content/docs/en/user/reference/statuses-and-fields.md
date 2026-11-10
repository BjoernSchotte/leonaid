---
title: Statuses and important fields
description: Reference for campaign, acquisition, order, invoice, and delivery statuses.
docId: DOC-P017
audience: [user]
diataxis: reference
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: dd69fcf4fed541649862cc2ed3c869415a3813d6
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
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

**Storniert** (cancelled) is final and only possible while the order is not
delivered and no payment is recorded on its invoice. The cancellation stores
the reason, an optional note, the previous status, who cancelled and when. A
cancelled order stays visible in lists but counts in no total and on no
delivery board; an open invoice is cancelled with it and gets a cancellation
invoice (see [Cancel an order](/en/user/how-to/cancel-order/)).

## Delivery window

| Technical     | Interface   | Meaning                                                                  |
| ------------- | ----------- | ------------------------------------------------------------------------ |
| open          | Buchbar     | offered in the order form, acquisition and the back office (bookable)    |
| `fullyBooked` | Ausgebucht  | not selectable publicly; back office and acquisition book after a prompt |
| `retired`     | Stillgelegt | no longer offered; booked orders keep their time (retired)               |

Retiring a window clears **Ausgebucht**. A window that has already started is
no longer offered.

## Invoice and delivery

Invoices are `issued` (**Ausgestellt**), `sent` (**Versendet**), `paid`
(**Bezahlt**), or `cancelled` (**Storniert**). The invoice list shows issued
or sent invoices with a remaining amount as **Offen**, and as **Überfällig**
after their due date. The status cannot be edited in the list; payment and
cancellation are explicit commands in the detail pane.

A cancellation issues a **cancellation invoice** ("Stornorechnung"): a
document of its own with the next number of the invoice number series, which
names the cancelled invoice. The number series belongs to the whole
installation. If money had been received for the invoice, it shows
**Erstattung offen** until someone records **Erstattung erledigt** (see
[Cancel an invoice](/en/user/how-to/cancel-invoice/)).

Email delivery has separate statuses: `queued`, `sending`, `retrying`,
`failed`, and `sent`. A delivery failure does not change the invoice. The PDF
is independently `pending`, `available`, or `deleted`.
