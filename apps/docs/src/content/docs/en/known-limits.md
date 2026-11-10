---
title: Known limits
description: Verified limits of the current LeonAid development and pilot state.
docId: DOC-P003
audience: [user, ops, dev]
diataxis: reference
contentRevision: 14
reviewedRevision: 14
verifiedAgainst: __SHA__
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

This documentation describes the current development state. It is not a
general production approval.

- The product interface and its outbound messages are currently in German.
  English guides quote German UI labels verbatim.
- One installation represents one club or isolated tenant. Shared
  multi-tenancy is not supported.
- Drivers tick off their assigned deliveries in the app (see
  [Work the delivery board](/en/user/how-to/work-delivery-board/)). Tour planning
  (feature flag `delivery.tours`, see
  [Plan delivery tours](/en/user/how-to/plan-delivery-tours/)) has limits: no
  road routing (straight-line distance only), no live tracking of drivers, one
  tour per driver and delivery day. The public Nominatim service and the OSM
  tiles are subject to their usage policies; for heavy use, configure your own
  provider.
- Notifications of the acquisition app (feature flag `pwa.push`, see
  [Switch on notifications](/en/user/how-to/switch-on-notifications/)) have
  limits: delivery through the push services of Google, Mozilla, Apple and
  Microsoft is not tested automatically, only sending to a decrypting
  receiver and the display in the browser; the check on a real Android phone
  and iPhone is manual. iPhone and iPad need LeonAid on the home screen.
  There are four kinds (follow-ups once a day from 8:00, new orders, tasks,
  deliveries), at most one notification per kind in 15 minutes, no quiet
  hours and no setting per device. A notification names a kind and a count
  only. It is a hint without a delivery guarantee. After a sign-out the
  member switches the device on again; after 90 days without opening the app
  nothing arrives until it is opened again. A member can register at most
  ten devices. A new `LEONAID_VAPID_PRIVATE_KEY` ends all device
  registrations; each device registers again by itself when its app is next
  opened.
- `finance_reader` can only read documents. The maintained demo user Finn
  Finanzen proves this read-only access. Payments and cancellation require
  `finance_manager` or the charity administrator for the affected campaign.
- Members cannot change their own login email. A system administrator starts
  the change and the new address must confirm it.
- Public orders require a published campaign with an active order form and an
  available offering. When delivery planning is enabled, an available delivery
  window is also required.
- The order confirmation and the cancellation notice are plain-text mails
  and go to buyers from the public form. For orders that members or acquirers
  enter, the campaign's managers switch them on per campaign (**E-Mails an
  Käufer**); an order is then confirmed once, as soon as it is ready for
  review. Orders without an e-mail address of the buyer and drafts get no
  e-mail, nor do orders that become ready for review only after the
  delivery, after the delivery window or after the campaign was completed;
  this also holds for orders from the public form. If LeonAid could send a
  confirmation that was created in time only after that (delivery
  disturbed), it is not sent any more and the order shows it as failed.
  The campaign's managers confirm orders from before the switch was set one
  by one in the order (**Senden**). The address is the sponsor's from the
  CRM. LeonAid does not check that the club's privacy notice names these
  e-mails. The e-mail on the delivery day (switched on per campaign, for
  orders of every origin) names the delivery window only: no arrival time
  per address, no driver, no message when a delivery is late or a window is
  moved. It goes out up to five minutes after the selected time and carries
  no link to the campaign page. A delivery window that ends before that time
  gets no e-mail; the order shows this. After the delivery, for cancelled
  orders and in a completed campaign it no longer goes out. Order numbers
  have two shapes: new ones are short (`LA-` and eight characters), public
  orders from before keep their long number. The campaign
  link points to the permanent address of the campaign on its campaign
  domain, else to the campaign page on the public host. The sender is the
  configured system address, not the club.
- The search (**Suchen und Befehle**) finds sponsors by name and city only,
  and only if they are assigned to an acquirer in a campaign (see
  [Find things with the search](/en/user/how-to/find-with-search/)). E-mail,
  phone and street cannot be searched. A change in the CRM reaches the search
  after up to about 15 minutes; a sponsor deleted in the CRM leaves the search
  only in the following night. Until then its result opens the assignment,
  which is then named "Im CRM nicht mehr vorhanden" and shows no contact data.
  The acquisition app has no search of its own.
- An issued invoice and its PDF are never overwritten. Corrections use a
  cancellation and a new transaction.
- A cancellation issues a cancellation invoice ("Stornorechnung") with its
  own number of the invoice number series. Only a full cancellation exists: no
  partial cancellation and no corrected invoice that replaces lines. An order
  has one invoice; a corrected invoice needs a new order. Invoices cancelled
  before this feature have no cancellation invoice until someone issues it.
  The wording of the cancellation invoice is a proposal and has no legal
  review yet.
- Donations are a capability of their own. A donation gets a number and a
  donation pledge ("Spendenzusage", a PDF, not an invoice) and can be recorded
  only while the part **Spenden** with the receiving body is active under
  **Rechtliches**. Only money donations in euro exist, one payment per
  donation and no collective receipt; a second part payment is a donation of
  its own. Only an unpaid donation can be cancelled. Donations are recorded
  in the back office only, not yet in the order form; you enter the donor by
  hand, there is no CRM search in that dialog yet. LeonAid does not issue
  the donation receipt yet. The wording blocks are proposals and have no
  legal review yet (see [Record a donation](/en/user/how-to/record-donation/)).
- Payments of a cancelled invoice stay recorded and cannot be reversed.
  LeonAid books no refund; "Erstattung erledigt" is only a marker. It can be
  taken back with a reason.
- Partial payments and overpayments are recorded as separate payment entries
  and can be reversed with a reason. An overpayment is only shown; the refund
  happens outside LeonAid. Bank reconciliation and dunning are missing.
- One installation serves one host, or an admin host (`app.<domain>`)
  plus a public host with redirecting extra names (stage 1 of
  `specs/multi-domain/PLAN.md`). Own campaign domains can be added, checked
  and bound to campaigns under **System › Domains**; they show only CMS
  campaign pages. Acceptance with a real domain and real certificates is open. An
  installation without a public host can be set up (`pilot-secrets --no-public-host`). `/` on the admin host is the role-based
  entry (sign-in, then the start area). Switching to two hosts signs
  every member out once (`pilot-revoke-sessions`). On the public host the
  header shows a static "Mitgliederbereich" link instead of the personal app links:
  the session belongs to the admin host.
- Campaign pages run in a pilot installation with `LEONAID_CMS_ENABLED=true`.
  Their one-time production setup (CMS database role, media bucket, editor
  setup) has no `pilot-*` command yet.
- Listmonk (Compose profile `mailing`) is not part of the pilot production
  stack. There it has no public route, no backup and no monitoring; all three
  must exist before the profile is enabled.
- The separate documentation website will be published as a static GitHub Pages
  site from the verified artifact. Until public acceptance, the versioned
  source and CI artifacts remain the reliable entry points.

## Documentation website information

Björn Schotte maintains the website through the public
[LeonAid repository](https://github.com/BjoernSchotte/leonaid). Problems can
be reported there as issues. The static site has no first-party analytics and
requires no sign-in. GitHub processes technical access data for hosting under
its [privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

LeonAid does not yet have an open-source license. The documentation does not
change that status; licenses for included components continue to apply.

Report a discrepancy with the affected product route, visible message, and
commit. The implementation remains the source of truth.
