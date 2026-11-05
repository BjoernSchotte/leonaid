---
title: Capture your first customer order
description: A learning path for acquirers from an assigned sponsor to an order ready for review.
docId: DOC-P011
audience: [user]
diataxis: tutorial
contentRevision: 3
reviewedRevision: 3
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

In this tutorial you act as an acquirer and capture a synthetic order for an
assigned sponsor. Use a demo installation with an active campaign, an
orderable offering, and, when delivery is enabled, a future delivery window.

## 1. Sign in and open the sponsor

1. Open `/login` on your LeonAid installation.
2. Enter your **Login-E-Mail** and select **Login-Code anfordern**.
3. Enter the **Sechsstelliger Code** from the most recent email and select
   **Anmelden**.
4. Select the **Sponsoren** tab at the bottom and tap the synthetic sponsor.
5. On the sponsor's page, select **Bestellung erfassen** (capture order).

LeonAid lists only sponsors assigned to you in this charity campaign. The
order is then titled **Bestellung für …** with the sponsor's name.

## 2. Choose the offering

The order has three steps: **Angebot** (offering), **Lieferung** (delivery)
and **Prüfen** (review).

1. Under **Angebot**, select a currently orderable item.
2. Set the quantity with **−** and **+** or type it. Use the **Summe** (total)
   for review; LeonAid recalculates the binding price when saving.
3. Select **Weiter** (next).

## 3. Enter delivery and billing

1. When delivery planning is active, enter the delivery address and select an
   available window. A retired or meanwhile changed window cannot be used for a
   new binding order.
2. Under **Rechnung** (billing), verify the name, **Straße und Hausnummer**,
   **PLZ**, and **Ort**. **Rechnungs-E-Mail** is optional.
3. Select **Weiter**.

Use synthetic names and addresses only. LeonAid stores the billing address as
a snapshot on the order.

## 4. Review and capture

Check the summary and select **Verbindlich erfassen** (capture as binding).
The confirmation shows **Bestellung erfasst**, the quantity, the sponsor, and
the server-calculated amount. The charity administrator can now find the item
under **Bestellungen** with status **Prüfbereit**. **Zurück zu …** returns to
the sponsor.

If delivery details are incomplete, select **Als Entwurf speichern**. Later use
**Entwurf abschließen** and **Entwurf prüfbereit abschließen**.

The form retains input after an error; **Zurück** (back) reaches every step. If
access is denied, open a sponsor assigned to you instead of repeating the
request.
