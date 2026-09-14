---
title: Record an invoice payment
description: Close an open invoice with the exact full payment after reconciling the bank transaction.
docId: DOC-P014
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

**Role:** global `finance_manager` or charity administrator for the affected
campaign. A `finance_reader`, including the demo user Finn Finanzen, can inspect
invoices and payment data but cannot record a payment.

1. Open **Rechnungen** in the back office and choose the correct
   **Charity-Aktion**.
2. Filter by **Offen** if needed and expand the item in **Belegjournal**.
3. Reconcile invoice number, recipient, gross amount, and payment reference
   with the actual bank transaction.
4. Select **Zahlung erfassen**.
5. Enter **Zahlungsbetrag**, **Geldeingang am**, and **Zahlungsreferenz**. The
   amount must exactly match the full open amount; partial payments and
   overpayments are rejected.
6. Select **Vollzahlung verbuchen**.

The card now displays **Vollständig bezahlt** and status **Erledigt**. The
payment record contains the amount, received date, reference, recording person,
and timestamp; the open amount becomes zero. Do not repeat the action once this
confirmation is visible.

If the control is absent, your account is read-only or the invoice is already
paid or cancelled. After an error the document remains open; reconcile the data
again and retry the same transaction in a controlled way.
