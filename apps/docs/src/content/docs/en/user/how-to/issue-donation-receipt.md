---
title: Issue a donation receipt
description: Issue the donation receipt for a paid donation, sign or send it, and declare it void after a mistake.
docId: DOC-P060
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 1c7cedc2a1d2733b336d30a146b28874c28e8eb1
reviewer: Claude Code (review by Björn Schotte pending)
---

**Role:** charity admin of the action or global `finance_manager`. Only the
charity admin of the action can send. `finance_reader` sees donation receipts
but cannot change anything.

The donation receipt ("Zuwendungsbestätigung") is the document a donor uses
to claim the donation in the tax return. LeonAid issues it after the official
sample for money donations. It confirms what arrived, not what was pledged.

The texts and rules have had no legal review yet. Have your tax adviser read
them before the first real use.

## Before you start

- The donation is **Bezahlt** (see
  [Record a donation](/en/user/how-to/record-donation/)).
- The notice of the receiving body is not too old. A Freistellungsbescheid
  and the Anlage zum Körperschaftsteuerbescheid carry donation receipts for
  five years from their date, a Feststellungsbescheid nach § 60a AO for three
  years. After that the donation shows a notice with the date, and a system
  admin enters the new notice under **Rechtliches** in the part **Spenden**.

## Issue the donation receipt

1. Open **Spenden** in the back office and choose the paid donation.
2. Choose **Zuwendungsbestätigung ausstellen**.
3. Check the amount and the day of the payment in the dialog. Both stand on
   the receipt afterwards and cannot be changed.
4. Confirm with **Zuwendungsbestätigung ausstellen**. Because a document is
   issued, you may have to confirm your login again.

The donation receipt gets a number of its own, for example **ZB26-0004**, and
the date of the day. The PDF is produced shortly after. It names the
receiving body, the donor, the amount in figures and in words, the day of the
donation, the notice, the privileged purposes and the liability note. The
list then shows the donation in the view **Bestätigt**.

A donation has only one valid donation receipt at a time.

## Sign or send

The part **Spenden** under **Rechtliches** sets how the receipt is signed.

- **eigenhändig** (by hand): the PDF has a signature line. Print it, have it
  signed and pass on the original. LeonAid does not send this receipt by
  e-mail, because it is valid only with a signature.
- **maschinell** (machine procedure): the PDF names the signatory and says
  that it was produced by machine and that the procedure was notified to the
  tax office. It is valid without a signature. Choose
  **Zuwendungsbestätigung senden** as soon as the PDF is ready. The e-mail
  goes to the donor's e-mail address. A failed delivery can be started again
  in the same area.

The receipt keeps the kind of signature that applied when it was issued.

## Declare a receipt void

An issued donation receipt is never changed. If it is wrong, declare it void
and issue a new one.

1. Choose **Für ungültig erklären** at the receipt.
2. Enter the **Grund**, at least eight characters.
3. Choose what happened to the original the donor holds: **Das Original
   liegt uns wieder vor** or **Das Finanzamt des Spenders ist informiert**.
   One of the two is required: otherwise the donor could hand in two receipts
   for one donation.
4. Confirm with **Für ungültig erklären**.

The receipt and its PDF stay stored and are listed under **Ungültige
Zuwendungsbestätigungen**. This cannot be undone. Afterwards you can issue a
new donation receipt; it gets the next number.

## Payment and donation receipt

While a valid donation receipt exists, the payment of the donation cannot be
taken back. Declare the receipt void first.

## Retention

The receiving body keeps a copy of every donation receipt. LeonAid stores
every receipt with its PDF, the void ones too. A privacy erasure keeps them
unchanged, like issued invoices.
