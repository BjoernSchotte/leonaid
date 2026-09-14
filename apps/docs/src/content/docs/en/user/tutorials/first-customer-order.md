---
title: Capture your first customer order
description: A learning path for acquirers from an assigned sponsor to an order ready for review.
docId: DOC-P011
audience: [user]
diataxis: tutorial
contentRevision: 1
reviewedRevision: 1
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
4. Open **Meine Sponsoren** and select **Bestellung** for the synthetic sponsor.

LeonAid lists only sponsors assigned to you in this charity campaign. The
sponsor appears as **Zugeordneter Sponsor** in the order form.

## 2. Enter the offering and invoice recipient

1. Under **Angebot**, select a currently orderable item.
2. Enter a **Menge** greater than zero. Use the displayed total for review;
   LeonAid recalculates the binding price on the server when saving.
3. Under **Rechnungsempfänger**, verify the name, **Straße und Hausnummer**,
   **PLZ**, and **Ort**. **Rechnungs-E-Mail** is optional.

Use synthetic names and addresses only. LeonAid stores the invoice recipient
as a snapshot on the order.

## 3. Enter delivery details and verify the result

When delivery planning is active, enter the delivery address and select an
available window. A retired or meanwhile changed window cannot be used for a
new binding order.

Select **Prüfbereit erfassen**. The result displays **Bestellung gespeichert**,
**Bereit für die Prüfung**, the customer, and the server-calculated total. The
charity administrator can now find the item under **Bestellungen** with status
**Prüfbereit**.

If delivery details are incomplete, select **Als Entwurf speichern**. Later use
**Entwurf abschließen** and **Entwurf prüfbereit abschließen**.

The form retains input after an error. Reload offerings and sponsors with
**Erneut versuchen**. If access is denied, open a sponsor assigned to you
instead of repeating the request.
