---
title: Record an invoice payment
description: Close an open invoice with the exact full payment after reconciling the bank transaction.
docId: DOC-P014
audience: [user]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 1c054b0fb55c59b9f884aee956b431a519ce521d
reviewer: Björn Schotte
---

**Role:** global `finance_manager` or charity administrator for the affected
campaign. A `finance_reader`, including the demo user Finn Finanzen, can inspect
invoices and payment data but cannot record a payment.

1. Open **Rechnungen** in the back office. If you look after several
   campaigns, choose the correct **Charity-Aktion** at the top right.
2. The **Offen** view lists every invoice with an open amount, **Überfällig**
   only those past their due date. Open the invoice with a click, or with
   the keys J/K and Enter.
3. Reconcile invoice number, recipient, gross amount, and payment reference in
   the detail pane with the actual bank transaction.
4. Select **Zahlung erfassen**.
5. In the dialog, enter **Eingegangener Betrag in €** and **Eingangsdatum**.
   **Verwendungszweck** is optional; when empty, the invoice's payment
   reference is used. The amount must exactly match the full open amount;
   partial payments and overpayments are rejected.
6. Confirm with **Zahlung erfassen**.

The invoice now carries the **Bezahlt** stamp and status **Bezahlt**. The
**Zahlung** section shows the amount, received date, reference, recording
person, and timestamp; the open amount becomes zero. The payment also appears
under **Zahlungen**, the list of all payments. Do not repeat the action once
this confirmation is visible.

If the control is absent, your account is read-only (the notice **Nur lesen.**
is shown above the list) or the invoice is already paid or cancelled. After an
error the invoice remains open; reconcile the data again and retry the same
transaction in a controlled way.
