---
title: Record a donation
description: Record a donation, send the donation pledge, book or take back the payment, and cancel a donation.
docId: DOC-P059
audience: [user]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: 72207916006de2ceab6bafc415460a2b6acb0879
reviewer: Claude Code (review by Björn Schotte pending)
---

**Role:** charity admin of the action or global `finance_manager`. Only the
charity admin of the action can send. `finance_reader` sees donations,
payments and donation pledges but cannot change anything.

A donation has nothing given in return. It therefore gets no invoice but a
**donation pledge** ("Spendenzusage"): a PDF with the amount, the donation
account and the number of the donation as payment reference. After the
payment arrived you issue the donation receipt for the tax return (see
[Issue a donation receipt](/en/user/how-to/issue-donation-receipt/)).

## Before you start

- The action has the capability **Spenden**. It is chosen when the action is
  created and can be changed while the action is a draft or scheduled.
- Under **Rechtliches** the part **Spenden** is filled in and active (see
  [Maintain the Impressum and privacy policy](/en/user/how-to/maintain-legal-pages/#receiving-body-for-donations)).
  It names the body that receives donations. Without it the page **Spenden**
  shows a notice, and no donation can be recorded.

The entry **Spenden** appears in the navigation under **Arbeit** as soon as
you may read or manage the finances of at least one action with this
capability.

## Record a donation

1. Open **Spenden** in the back office and choose the action at the top.
2. Choose **Spende erfassen**.
3. If the action has sponsors from acquisition and you manage it, you can
   search a sponsor of this action by name or city under **Spender im CRM
   suchen** and choose it with **Übernehmen**. Name, postal code, city and
   e-mail are then filled in, and the donation is linked to the CRM contact.
   You type the street yourself.
4. Enter or check **Name des Spenders**, **Straße und Hausnummer**,
   **Postleitzahl** and **Ort**. Write the name as the donation receipt shall show it later.
5. Enter the **E-Mail** if you want to send the donation pledge by e-mail.
   The field is optional.
6. Enter the **Betrag in €**, from 1.00 € to 1,000,000.00 €. This is the
   pledged amount.
7. Confirm with **Spende erfassen**. Because a document is issued, you may
   have to confirm your login again.

The donation gets a number from the series of donation pledges at once, for
example **SP26-0007**. The series applies to the whole installation. Name,
address and amount cannot be changed afterwards. To correct a mistake, cancel
the donation and record it again.

## Donation with an order

An action can offer a voluntary extra donation in its order form.

- **Switch on:** open the action and switch on **Zusatzspende im
  Bestellformular anbieten** in the area **Zusatzspende im Bestellformular**.
  This also works while the action runs. The action needs the capability
  **Spenden**, and the part **Spenden** must be active under **Rechtliches**;
  otherwise no form shows the field. Actions from the template
  **Krapfentaxi** from version 3 on have both already.
- **Public form:** buyers enter an amount from 1.00 € to 10,000.00 € under
  **Zusätzlich spenden**. The donation is created at once with its own
  number, and the donation pledge goes to the buyer by e-mail by itself.
- **Capture by members:** the back office and the acquisition app have the
  field **Zusatzspende in €**. For a draft LeonAid keeps only the amount; the
  donation is created when the order becomes binding. You then send the
  donation pledge yourself.
- The **donor** is always the invoice recipient of the order. An order with
  a donation therefore needs a complete invoice recipient.
- The donation is not part of the order total and is not on the invoice. The
  order shows it with number and state and links to it.
- If the order is cancelled, an unpaid donation is cancelled with it while
  you keep the tick in the dialog (see
  [Cancel an order](/en/user/how-to/cancel-order/)).

## View and send the donation pledge

Open the donation in the list. The section **Spendenzusage** shows number and
date. The PDF is produced shortly after the donation is recorded; you can
then view and download it. It is also listed under **Rechnungen** in the view
**Dokumente**.

The donation pledge shows name, address, tax office, tax number and account
of the receiving body, not those of the invoice issuer. It is not an invoice
and has no tax lines.

In the area **Versand der Spendenzusage** choose **Spendenzusage senden** as
soon as the PDF is ready. The e-mail goes to the donor's e-mail address with
the PDF attached. The area then shows whether the e-mail was delivered. A
failed delivery can be started again there. **Erneut senden** sends the same
donation pledge once more on purpose.

If no e-mail address is stored, LeonAid cannot send the donation pledge:
download the PDF and pass it on another way.

## Record the payment

1. Open the donation and choose **Zahlung erfassen**.
2. Check the amount received (**Eingegangener Betrag in €**). The pledged
   amount is filled in. If more or less arrived, enter what arrived.
3. Enter the **Eingangsdatum**: the day the money arrived. The donation
   receipt shows it later. It may lie before the day of the pledge if the
   money was there earlier, but not in the future.
4. Confirm with **Zahlung erfassen**.

The donation is then **Bezahlt**. The amount received counts, not the pledge.
The detail area names the difference.

A donation has exactly one payment. If a donor pays in two parts, record the
second part as a donation of its own.

## Take back a payment

If you booked a payment on the wrong donation, choose **Zahlung
zurücknehmen** in the section **Zahlung** and enter the **Grund der
Rücknahme**, at least eight characters. The donation is **Offen** again.
**Zurückgenommene Zahlungen** keeps what was recorded, who recorded it and
who took it back.

If the payment has a valid donation receipt, declare that receipt void first.

## Cancel a donation

Only a donation without a recorded payment can be cancelled. Choose **Spende
stornieren** and enter the **Grund der Stornierung**. The donation stays with
its number, data and donation pledge but no longer counts as an open pledge.
A cancellation cannot be taken back.

For a paid donation, take back the payment first.

## Totals

The page **Spenden** shows **Eingegangen** and **Zugesagt, noch offen** for
the chosen action at the top. The overview of the action names both sums
under **Weitere Kennzahlen**.

## Privacy

Donations and their documents are tax records. A privacy erasure names the
donations of the person but keeps them unchanged for the approved retention
period, like issued invoices.
