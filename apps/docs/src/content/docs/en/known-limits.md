---
title: Known limits
description: Verified limits of the current LeonAid development and pilot state.
docId: DOC-P003
audience: [user, ops, dev]
diataxis: reference
contentRevision: 7
reviewedRevision: 7
verifiedAgainst: e0a3533c57747a914cde695a334e31fb90ffbc60
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

This documentation describes the current development state. It is not a
general production approval.

- The product interface and its outbound messages are currently in German.
  English guides quote German UI labels verbatim.
- One installation represents one club or isolated tenant. Shared
  multi-tenancy is not supported.
- Drivers tick off their assigned deliveries in the app (see
  [Work the delivery board](/en/user/how-to/work-delivery-board/)). Route and tour
  planning is outside the current scope.
- `finance_reader` can only read documents. The maintained demo user Finn
  Finanzen proves this read-only access. Payments and cancellation require
  `finance_manager` or the charity administrator for the affected campaign.
- Members cannot change their own login email. A system administrator starts
  the change and the new address must confirm it.
- Public orders require a published campaign with an active order form and an
  available offering. When delivery planning is enabled, an available delivery
  window is also required.
- The order confirmation and the cancellation notice are plain-text mails and
  go only to buyers from the public form. Orders that members or acquirers
  enter send no e-mail. The campaign link points to the campaign page on the
  public host; own campaign domains follow with stage 2. The sender is the
  configured system address, not the club.
- An issued invoice and its PDF are never overwritten. Corrections use a
  cancellation and a new transaction.
- Partial payments and overpayments are recorded as separate payment entries
  and can be reversed with a reason. An overpayment is only shown; the refund
  happens outside LeonAid. Bank reconciliation and dunning are missing.
- One installation serves one host, or an admin host (`app.<domain>`)
  plus a public host with redirecting extra names (stage 1 of
  `specs/multi-domain/PLAN.md`). Own campaign domains can be added under
  **System › Domains** and bound to campaigns; they are not served yet. An
  installation without a public host is only specified. `/` on the admin host is the role-based
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
