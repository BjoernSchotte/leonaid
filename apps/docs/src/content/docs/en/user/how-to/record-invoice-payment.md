---
title: Record an invoice payment
description: Record full, partial, and overpayments of an invoice and reverse a wrong entry.
docId: DOC-P014
audience: [user]
diataxis: how-to
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 68fe0e63b592a739925654788509e63a71b01e8a
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

**Role:** global `finance_manager` or charity administrator for the affected
campaign. A `finance_reader`, including the demo user Finn Finanzen, can inspect
invoices and payment data but cannot record or reverse a payment.

## Record a payment

1. Open **Rechnungen** in the back office. If you look after several
   campaigns, choose the correct **Charity-Aktion** at the top right.
2. The **Offen** view lists every invoice with an open amount, including
   **Teilweise bezahlt**; **Überfällig** only those past their due date. Open
   the invoice with a click, or with the keys J/K and Enter.
3. Reconcile invoice number, recipient, open amount, and payment reference in
   the detail pane with the actual bank transaction.
4. Select **Zahlung erfassen**. On paid or overpaid invoices the control is
   called **Weitere Zahlung erfassen**.
5. **Eingegangener Betrag in €** is prefilled with the open amount. If the
   full amount arrived, change nothing. Otherwise enter the amount actually
   received; the hint below the field shows what stays open or how much was
   paid too much.
6. Enter **Eingangsdatum**. **Verwendungszweck** is optional; when empty, the
   invoice's payment reference is used. **Notiz** is optional, for example
   "Rest kommt im Dezember".
7. Confirm with **Zahlung erfassen**.

Each payment is its own entry in the **Zahlungen** section with amount,
received date, reference, note, recording person, and timestamp. The status
follows from the sum of all entries:

| Sum of entries          | Status                | What you see                                        |
| ----------------------- | --------------------- | --------------------------------------------------- |
| less than the amount    | **Teilweise bezahlt** | **Eingegangen** and the remaining **Offen** amount  |
| exactly the amount      | **Bezahlt**           | stamp **Bezahlt**, open amount 0,00 €               |
| more than the amount    | **Überzahlt**         | stamp **Überzahlt** and **Differenz erstatten**     |

For an overpayment, transfer the difference back to the sponsor outside
LeonAid. LeonAid does not book a refund. Every entry also appears under
**Zahlungen**, the list of all payments. Do not repeat the action once the
confirmation is visible.

## Reverse a wrong entry

An entry is never deleted. If you recorded a wrong amount or the wrong
invoice, or the bank returned a direct debit:

1. Open the invoice and select **Zurückbuchen** at the entry in the
   **Zahlungen** section.
2. Enter **Grund der Rückbuchung** with at least eight characters.
3. Confirm with **Zurückbuchen**.

The entry stays visible, struck through, with reason, person, and timestamp,
and no longer counts toward the sum. The open amount and the status are
recalculated. Then record the correct amount again if needed.

## If something goes wrong

- If the control is absent, your account is read-only (the notice **Nur
  lesen.** is shown above the list) or the invoice is cancelled.
- If the dialog reports that the payments changed in the meantime, someone
  else booked at the same time. Reload the page, check the open amount, and
  record the payment only if it is still missing.
- After any other error the invoice stays unchanged. Reconcile the data again
  and retry the same transaction in a controlled way.
