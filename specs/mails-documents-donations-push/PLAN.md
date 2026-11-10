# Buyer mails, cancellation invoice, donations, sponsor search, push

Status: 2026-11-10, written on Björn's order of the same day ("als ein
Bündel implementieren"). Björn asked for no questions before the build
(standing rule of 2026-11-08): every decision in §12 marked **(lead)** is the
lead's call and is open to his correction. §13 lists what only he can sign.

## 1. Context

Six gaps of `specs/leonaid-poc/KNOWN-LIMITS.md`, ordered by Björn as one
bundle on 2026-11-10, plus two additions of the same day:

1. Order confirmation and cancellation mails only go to buyers of the public
   form. Orders entered by members or acquirers send nothing.
2. There is no mail on the delivery day, and no way to send a mail again.
3. A cancelled invoice keeps its number and PDF; there is no cancellation
   document ("Stornorechnung").
4. LeonAid knows no donations and issues no donation receipts.
5. The core search finds no sponsors.
6. The PWA sends no push notifications.

Additions: donations become a **generic capability** of an action, and the
Krapfentaxi order form gets an optional "I also want to donate" amount that
produces a **second, separate document**.

Facts the design rests on (recon of main at `45b40213`):

- `mail_due()` (`application/order_mails.py:495`) sends only for
  `PUBLIC_FORM`. Internal orders have no buyer-facing number:
  `ck_commitment_public_reference` and `domain/commitments.py:514` forbid
  `public_reference` for them.
- The outbox claims jobs with `available_at <= now`. The worker has
  `BackgroundLoop`s (survey sweep, retention, geocoding) but no scheduler.
- Capabilities lock once an action leaves draft or scheduled
  (`domain/actions.py:369`). A switch the club changes while the action runs
  is a settings row, like `action_delivery_configuration`.
- Invoice numbers: one counter per action (`invoice_profile.next_number`),
  one prefix for the installation, `invoice.number` unique for the
  installation. Two actions with the same prefix collide.
- No application code creates an `invoice_profile` row (only seed and smoke).
- `Money >= 0`, line quantity `> 0`, one invoice per order, one document type
  (`invoice_pdf`), and the render job joins `invoice`.
- Core keeps no copy of CRM parties. A sponsor is visible through core only
  by an `acquisition_assignment` of an action.
- The PWA service worker has no push handler. `cryptography` and `httpx` are
  direct dependencies; `pywebpush` is not installed.

## 2. Goals

- **G1.** Every order has an order number the buyer can quote.
- **G2.** An action can switch on buyer mails for orders that members and
  acquirers enter: confirmation and cancellation notice.
- **G3.** An action can switch on a delivery-day mail: "your delivery comes
  today between 10:00 and 12:00".
- **G4.** The order detail shows which mails went to the buyer, and a
  manager can send one again.
- **G5.** Cancelling an issued invoice issues a cancellation invoice with its
  own number, its own PDF and a reference to the original.
- **G6.** Donations are a capability of an action: recorded, numbered,
  paid, and receipted with a donation receipt ("Zuwendungsbestätigung").
- **G7.** The Krapfentaxi order form offers an optional extra donation. It
  becomes a donation with its own document, never a line of the invoice.
- **G8.** The search finds the sponsors a user may see.
- **G9.** Members can switch on push notifications in the PWA for work that
  waits for them.

## 3. Non-goals

- No HTML mails, no club-specific sender address, no mail templates editable
  in the UI.
- No arrival time per stop and no live tracking in the delivery-day mail.
- No partial cancellation of an invoice and no corrected invoice that
  replaces lines. A correction stays "cancel, then issue again".
- No refunds booked in LeonAid, no bank import, no payment provider.
- No donations in kind ("Sachspenden"), no waiver of reimbursement
  ("Aufwandsspenden"), no membership fees, no yearly collective receipt.
- No public donation page without an order. (The capability carries it; the
  page is a later step.)
- No e-mail, phone or street of a sponsor in the search index.
- No push in the web admin, no SMS, no names of third persons in a push
  payload.

Anti-goals: a donation on an invoice; a receipt for money that did not
arrive; a mail to a buyer after erasure; a second mail by a retry storm.

## 4. Terms

| Term | Meaning |
|---|---|
| Order number | `commitment.public_reference` (`LA-…`), from now on for every order. |
| Buyer mail | A plain-text mail to the buyer of one order: confirmation, cancellation notice, delivery day. |
| Document series | A gapless counter for one kind of document and one prefix, for the whole installation. |
| Cancellation invoice | "Stornorechnung": a document with its own number from the invoice series, negative amounts, and the number and date of the invoice it cancels. |
| Donation | Money given without anything in return, for the purpose of the action. |
| Donation pledge | "Spendenzusage": the numbered document that asks the donor to pay the donation. Not an invoice. |
| Donation receipt | "Zuwendungsbestätigung" after § 10b EStG, issued for money received. |
| Receiving body | The tax-privileged body that receives donations and signs receipts (often the club's "Förderverein"). |

## 5. Foundations (stage 1 and stage 3)

### 5.1 Order number for every order

- `public_reference` is set for every new order, whatever its source, at
  creation (also for a draft; an order from the offline queue gets it when
  the server stores it).
- Migration: drop `ck_commitment_public_reference`, backfill existing orders
  without a number with the same generator, add `NOT NULL`.
- The number of a new order is short, so that a buyer can read it out on the
  phone: `LA-` plus 8 characters of an alphabet without `0`/`O` and
  `1`/`I`/`L`, unique. The backfill uses the same form. Numbers that public
  orders already have (`LA-` plus 32 hex digits) stay valid: buyers hold
  them (ruling on the review of PR #216).
- The domain rule `commitment_public_reference_forbidden` goes.
  `order_reference()` in the delivery board loses its fallback.
- The order detail, the order list, the delivery board and the invoice PDF
  subject line show the number where they show the fallback today. The
  column name stays (renaming it is an OpenAPI break without a gain).

### 5.2 Document series (ADR-0015)

ADR-0004 says "Der Nummernkreis gilt pro Aktion und Präfix". With one prefix
for the installation that rule produces duplicate numbers. ADR-0015 replaces
the sentence:

- New table `document_series(kind, prefix, next_number, width)`, primary key
  `(kind, prefix)`. Kinds: `invoice`, `donation`, `donation_receipt`.
- A number is allocated in the transaction of its document: row lock, then
  compare-and-swap, as today. A failed transaction uses no number.
- Migration: one `invoice` row per prefix in use, with `next_number` = the
  highest `next_number` of the profiles with that prefix, and never below
  the highest issued number + 1. `invoice_profile.next_number` stays in the
  table for one release as a read-only mirror and is no longer the source.
- The cancellation invoice takes its number from the **invoice** series
  (D-C1). Donation pledges and donation receipts have their own series and
  prefixes, set in the legal configuration (§8.1).

### 5.3 Invoice profile for every action with invoicing

- Activating a legal configuration already syncs issuer data into all
  profiles. From now on a profile row is also created when an action gets
  the `invoicing` capability (at creation or by `set_capabilities`) and, by
  migration, for every existing action with `invoicing` and no profile.
- The row is unconfirmed until a legal configuration is active; issuing
  still answers `invoice_profile_missing` or the existing "incomplete"
  state, as today.

## 6. Buyer mails (stages 1 and 2)

### 6.1 Switches per action

New settings row `action_buyer_mail_configuration`, one per action, created
with the action and by migration for existing ones:

| Column | Default | Meaning |
|---|---|---|
| `internal_order_mails` | false | Confirmation and cancellation notice for orders with source `acquisition` or `admin`. |
| `delivery_day_mail` | false | The delivery-day mail, for orders of every source. |
| `delivery_day_send_time` | 07:00 | Local time of the action (`action_delivery_configuration.timezone`). 05:00–12:00. |
| `revision` | 1 | Optimistic lock. |

- Mails for public-form orders stay as they are: always sent, not behind a
  switch (D-M1).
- API: `GET`/`PUT /api/v1/actions/{id}/buyer-mail-configuration`, manager
  only, no status lock. `delivery_day_mail` needs the `delivery` capability.
- UI: a section "E-Mails an Käufer" in the action's settings, two switches
  and the time. Each switch says what the buyer gets and when.

### 6.2 Confirmation and cancellation for internal orders

- `mail_due()` becomes: the order has a buyer e-mail, and (source is
  `PUBLIC_FORM`, or the action has `internal_order_mails`).
- The confirmation is enqueued when an internal order **becomes
  `review_ready`** (at creation with `ready_for_review`, or by
  `completeCommitment`), in that transaction. A draft sends nothing.
- A change of window or address after that (`completeCommitmentDelivery`)
  sends no second confirmation. The delivery-day mail carries the final
  window.
- The cancellation notice follows the same rule as today, with the new
  `mail_due()`.
- The text for internal orders differs in one sentence: who recorded the
  order ("Ihre Bestellung wurde von einem Mitglied des … für Sie
  erfasst."), and it links the privacy notice. There is no consent record
  for these buyers; the legal basis is the contract (§13, P1).
- The UI helper `notifiesBuyer()` in `order-cancellation.tsx` follows the
  server: the cancellation dialog reads the fact from the order record
  (`buyerMailDue`), not from a copy of the rule.

### 6.3 Delivery-day mail

- Job `order.delivery_day.mail.v1`, key
  `order-delivery-day-mail:{commitmentId}:{windowId}`.
- A new worker loop `delivery_day_mail_sweep` (every 5 minutes, singleton by
  advisory lock) enqueues the job for each order where all of this holds:
  the action has `delivery_day_mail`; the order's window starts **today** in
  the action's zone; local time is at or after `delivery_day_send_time` and
  before the window ends; the order is `review_ready`, `confirmed` or
  `invoiced`; no drop state is recorded; the buyer has an e-mail; no ledger
  row and no pending job exists for the key.
- The handler reads the facts again at send time and skips when the order
  was cancelled, delivered, erased or moved to another window meanwhile.
  A moved order gets the mail for its new window from the sweep (new key).
- Text: the window ("Ihre Lieferung kommt heute, Samstag, 05.12.2026,
  zwischen 10:00 und 12:00 Uhr."), the delivery address, the quantities, the
  club's contact, the imprint block. No driver name, no phone of a driver.
- The mailbox limit of 10 mails per hour applies. A sweep, not future-dated
  jobs: switching the feature, moving an order and closing a window need no
  job bookkeeping (D-M2).

### 6.4 Mail status and "send again"

- `GET /api/v1/actions/{id}/commitments/{id}/buyer-mails` lists one entry
  per kind that applies: `kind`, `state` (`not_due`, `queued`, `sent`,
  `failed`, `skipped`), `sentAt`, `reason` for `not_due`/`skipped`/`failed`
  (`no_email`, `switched_off`, `order_cancelled`, `recipient_limit`, …).
  Source: `mail_delivery` and `outbox_event`.
- `POST …/buyer-mails/{kind}/resend`, manager, `Idempotency-Key`. It
  enqueues a new job with the key `…:resend:{n}`. Allowed for `sent` and
  `failed`; refused when the mail is not due (no e-mail, cancelled order for
  a confirmation, delivered order for the delivery-day mail). The mailbox
  limit applies.
- The ledger join in `recent_order_mails()` keeps working: the commitment
  id stays the second key segment.
- UI: a block "E-Mails an den Käufer" in the order detail: one row per kind
  with state and time, and "Erneut senden" where allowed. Audit event
  `order_mail_resent`.

## 7. Cancellation invoice (stage 3)

- Cancelling an invoice (`cancelInvoice`, and `cancelCommitment` for an
  issued, unpaid invoice) issues the cancellation invoice **in the same
  transaction**: number from the invoice series, `issued_on` = today in the
  club's zone, a snapshot that copies issuer, recipient, tax case and lines
  of the original with negated amounts, and the original's number and date.
- Storage: `invoice_cancellation` gets `number` (unique, also unique against
  `invoice.number` by a shared unique table `document_number(number)`),
  `issued_on`, `snapshot`, `document_version`. The original invoice is not
  touched: status `cancelled`, number, snapshot and PDF stay (ADR-0009).
- Amount types stay non-negative: the snapshot stores the original amounts
  and the document prints them with a minus sign. The domain type for the
  cancellation document owns that rule.
- PDF: template `invoice-cancellation-v1.typ`, title "Stornorechnung
  {nr}", line "zur Rechnung {nr} vom {date}", the reason is **not**
  printed. New document type `invoice_cancellation_pdf`; the render job and
  the handler get a second branch, the storage key gets
  `…/cancellations/{id}/…`.
- Paid invoices: `cancelInvoice` keeps cancelling them. The document then
  states the amount already received and "Die Erstattung erfolgt
  gesondert.". Payments of a cancelled invoice cannot be reversed (ADR-0014,
  `invoice_settlements.py:322`), and that stays. Instead
  `invoice_cancellation` gets `refund_settled_on` and `refund_note`: the
  invoice list shows "Erstattung offen" until a manager records "Erstattung
  erledigt" (date, optional note, audited). `cancelCommitment` still refuses
  while a payment is active (unchanged, D-C3).
- Sending: the cancellation invoice goes to the invoice recipient with the
  same delivery flow as an invoice (`sendInvoiceCancellation`, retry,
  status). When the original was sent by mail, the cancel dialog offers
  "Stornorechnung gleich senden", on by default.
- Invoices cancelled before this stage have no document. The invoice detail
  offers "Stornorechnung ausstellen" for them (manager, fresh login); no
  migration invents documents.
- The false text in `ui-system-catalog.tsx:882` becomes true; the dialog
  text in `invoice-dialogs.tsx:348` is rewritten.
- OpenAPI: `document_type` gains a value (breaking by the checker's rule).
  The lead prepares the approval entry (E-045).

## 8. Donations (stages 4 to 6)

### 8.1 Receiving body in the legal configuration

A new part "Spenden" in the legal configuration (four-eyes flow as today):

- receiving body: name, address, legal form;
- tax office, tax number;
- kind of notice: "Freistellungsbescheid", "Anlage zum
  Körperschaftsteuerbescheid" or "Feststellungsbescheid nach § 60a AO", its
  date, and for the first two kinds the assessment period;
- the privileged purposes as the notice names them;
- bank details for donations (may differ from the invoice account);
- signatory name and function for the receipt;
- how receipts are signed: `by_hand` (default) or `machine`. `machine`
  means the body has notified its tax office of the machine procedure
  (R 10b.1 Abs. 4 EStR) and needs the date of that notice;
- prefixes and width of the series `donation` and `donation_receipt`;
- wording blocks of pledge and receipt, with the proposals from
  `legal-templates.ts` marked "LEGAL REVIEW PENDING".

The part is optional: a club without donations activates its legal
configuration without it. Without an active configuration that has this
part, no donation can be recorded anywhere: the admin form says what is
missing and where, the order forms do not show the donation block (the
flag of §8.6 has no effect), and the server refuses a donation amount. So
every donation has a number from its first moment (D-D6).

The receiving body may be another legal entity than the invoice issuer.
Pledge and receipt, and the mails that carry them, show the receiving
body's name, address and bank details, never the issuer's. The order form
names the body in its donation sentence, and the privacy notice says that
the donor's name and address go to it (§13, P6).

### 8.2 Capability `donations`

- New value in `ActionCapability`, no dependency on other capabilities.
- Migration widens both CHECK constraints. No template gets it by
  migration except the new Krapfentaxi version (§8.6).
- OpenAPI enum change: approval entry by the lead (E-045).
- Navigation: "Spenden" in the web admin under "Arbeit", shown when the
  user manages or reads finance for at least one action with the
  capability.

### 8.3 Model

`donation`:

| Field | Notes |
|---|---|
| `id`, `action_id` | |
| `number` | From the `donation` series, when the receiving body is configured. Unique. |
| `donor_snapshot` | Name, street, postal code, city, country, e-mail (optional), CRM party id (optional). |
| `pledged_minor`, `currency` | `> 0`, EUR. What the donor promised. |
| `received_minor`, `received_on`, `payment_note` | Null until the payment is recorded. One payment per donation (D-D7). |
| `source` | `public_form`, `admin`, `acquisition`. |
| `commitment_id` | Set when the donation came with an order. |
| `status` | `pledged`, `paid`, `cancelled`. |
| `pledged_at`, `created_by` | |

Payment: "Zahlung erfassen" records the day and the amount that arrived,
once. The amount may differ from the pledge in either direction; the
donation is then `paid` with what arrived, and the receipt confirms that
amount. "Zahlung zurücknehmen" (with a reason, audited) puts the donation
back to `pledged` as long as it has no valid receipt. A donor who pays in
two parts gets the second part recorded as a second donation by the
manager.

`donation_receipt`: `number` from its series, `donation_id`, `issued_on`,
`snapshot` (receiving body, donor, amount in figures and words, day of the
donation, the wording blocks in force), `voided_at`, `void_reason`,
`void_evidence` (`original_returned` or `tax_office_informed`).

Rights: read as invoices (`may_read_invoices`); record payments, issue
receipts, cancel: action manager or global finance manager; issuing and
cancelling need a fresh login. Audit events for every write.

### 8.4 Pledge document

- A donation with a number gets the PDF "Spendenzusage {nr}" at once
  (render job, document type `donation_pledge_pdf`): amount, purpose of the
  action, bank details, the number as payment reference, the sentence that
  nothing is given in return, and that the receipt follows after payment.
- It is not an invoice: no tax lines, no "Rechnung" in the title (D-D2).
- Sending: by mail to the donor, with the flow of §7. Automatic when the
  donation came through the public form; a button otherwise.

### 8.5 Donation receipt

- "Zuwendungsbestätigung ausstellen" is offered when the donation is
  `paid` and has no valid receipt. One receipt per donation, always the
  single form: amount received, day received.
- Issuing is refused when the notice is too old for § 63 Abs. 5 AO: more
  than 5 years since the date of a Freistellungsbescheid or of the
  Körperschaftsteuerbescheid, more than 3 years since a notice after
  § 60a AO. The UI names the date and the part of the legal configuration
  to renew.
- Signature: with `by_hand` the PDF has an empty signature line under the
  signatory's name, the UI says "Ausdrucken und unterschreiben", and the
  receipt cannot be sent by mail from LeonAid. With `machine` the PDF
  carries the signatory's name and the sentence that it was produced by
  the machine procedure notified to the tax office, and it can be sent as
  a PDF by mail.
- The PDF follows the official sample for money donations to bodies of
  § 5 Abs. 1 Nr. 9 KStG: receiving body, donor, amount in figures and
  words, day of the donation, "Es handelt sich nicht um den Verzicht auf
  Erstattung von Aufwendungen", the notice paragraph for the configured
  kind of notice, the purposes, the liability note, place, date, signatory.
  Document type `donation_receipt_pdf`.
- Amount in words: a small German number-to-words function with tests
  (0 to 999 999 999, cents as "xx/100").
- A receipt is immutable. "Für ungültig erklären" voids it with a reason
  (fresh login) and with what happened to the paper the donor holds: the
  original came back, or the tax office was informed. Without one of the
  two no new receipt can be issued for that donation. The PDF stays
  stored. Taking back the payment of a receipted donation is refused until
  the receipt is voided.
- Sending by mail as in §7 (only with `machine`). Retention 10 years; erasure keeps donation and
  receipt with a retention reason, as for invoices.

### 8.6 Extra donation in the order form

- `OrderFormConfiguration` and both form tables get `allow_donation`
  (default false). It may only be true when the action has `donations`.
- New Krapfentaxi template version 3: version 2 plus the `donations`
  capability and `allow_donation = true`. Existing actions keep their copy;
  a manager can switch the flag in the form settings once the capability is
  on (capabilities lock after `scheduled`, so a running action cannot get
  it; that is the existing rule and stays, D-D4).
- Form (apps/public and apps/campaign-site): after the lines, an optional
  block "Zusätzlich spenden" with an amount in euro (whole or with cents,
  1.00 to 10 000.00), and the sentence "Ihre Spende ist freiwillig und ohne
  Gegenleistung. Empfänger ist der {receiving body}. Sie erhalten dafür
  eine eigene Zahlungsbitte, getrennt von der Rechnung für Ihre
  Bestellung." The total of the order does not
  include it; a second line shows "Spende: … €".
- API: `CreatePublicOrderRequest.donationAmountMinor` (optional). It is
  part of the idempotency fingerprint. The server refuses it when the form
  does not allow it.
- The amount is stored on the order: `commitment.donation_pledge_minor`
  (nullable). The donation row is created, with its number, in the
  transaction in which the order becomes `review_ready`: at once for a
  public order (`_record_order`), at completion for an internal draft.
  Donor = the order's invoice recipient, `commitment_id` set. An order with
  a donation amount needs a complete invoice recipient to become
  `review_ready`.
- The order confirmation mail names the donation in its own paragraph and
  says that the pledge comes as a separate mail.
- Cancelling the order: the dialog shows an unpaid donation of the order
  with "Spende ebenfalls stornieren", on by default. A paid donation is
  never cancelled with the order.
- Members and acquirers can add a donation to an internal order in the
  capture form the same way (web and PWA; in the offline queue the amount
  travels in the stored request). A draft keeps only the amount.

### 8.7 Admin UI

- "Spenden": list per action (number, donor, amount, state, receipt),
  filters open/paid/receipted/cancelled, sum received.
- "Spende erfassen": donor (CRM search or free entry), amount, note.
- Detail: documents, payments with "Zahlung erfassen" and "Zurückbuchen",
  receipt, mails, link to the order.
- The dashboard's "Spendenziel" stays as it is; the donation sum is shown in
  the action overview next to the order figures.

## 9. Sponsors in the search (stage 7)

- Table `sponsor_search_entry(party_kind, twenty_id, display_name, city,
  synced_at)`, primary key `(party_kind, twenty_id)`. Nothing else: no
  e-mail, phone or street (D-S1).
- Filled only for parties that have an `acquisition_assignment`:
  - on assignment creation, with the name core already holds from the
    resolution;
  - by a worker loop every 15 minutes: parties changed in Twenty in the last
    30 minutes (`updatedAt` filter) that are in the table;
  - by a full pass once a night: every referenced party is read in ID
    batches, entries without an assignment or without a CRM record are
    deleted.
  The loop spends at most 30 CRM requests per run and stops on the first
  429: the limit of 100 per minute counts per process, and the API needs
  the rest.
- Search: one more query, `ILIKE` on `display_name` and `city`, joined to
  `acquisition_assignment` for the scope of `authorized_scope`: managers see
  all assignments of their actions, acquirers their own that are not handed
  over. One hit per assignment.
- Hit: type `sponsor`, title = name, context = action and city. Target:
  managers `/admin/acquisition?action={id}&open={assignmentId}` (the table
  scrolls to the row, marks it and opens its detail), acquirers
  `/app/sponsors?action={id}&assignment={assignmentId}`.
- The group label of the palette names sponsors. The missing system-admin
  bypass of the action-scope board (`activities.py:761`) is fixed, so a
  system admin can open the target.
- Erasure: a `PrivacySubjectContributor` deletes the entries of the erased
  party; the nightly pass removes what Twenty no longer has.
- No OpenAPI change: `sponsor` is in the enum already.

## 10. Push notifications (stage 8)

- Web Push with VAPID. Sending is implemented in core with `cryptography`
  and `httpx` (RFC 8291 `aes128gcm`, RFC 8292), tested against the RFC's
  vector. No new dependency (D-P1).
- Keys: `LEONAID_VAPID_PRIVATE_KEY` (P-256, generated by `bootstrap` and the
  pilot secret generation) and `LEONAID_VAPID_SUBJECT` (mailto of the
  operator). Without the key the feature reports "not configured".
- Global flag `pwa.push`, default off, client-safe.
- Table `push_subscription`: user, endpoint (unique), keys, user agent,
  created, last success, failure count. Only endpoints of known push
  services are accepted (FCM, Mozilla, Apple, Windows; list in code) to
  rule out requests to other hosts. A 404 or 410 deletes the row; signing
  out on the device unsubscribes.
- Table `push_preference(user_id, kind, enabled)`.
- Kinds, all opt-in per user in "Benachrichtigungen" of the PWA:
  - `follow_ups`: once a day at 08:00 club time, when follow-ups are due or
    overdue: "3 Wiedervorlagen sind fällig."
  - `feed`: a new entry in "Neues" for the user: "Neue Bestellung zu einem
    Ihrer Sponsoren."
  - `tasks`: a task was assigned to the user.
  - `delivery`: stops were assigned to the driver for a day.
- Payloads carry a kind, a count and a target path. No name, address or
  amount (D-P2): the text passes through the push services.
- Server: an outbox job `push.notification.v1` per user and event; the
  handler sends to each subscription, at most one push per user and kind in
  15 minutes (later ones are merged into the count). The daily follow-up
  push comes from a worker loop.
- Service worker: `push` shows the notification, `notificationclick` opens
  or focuses the PWA at the target path. Build stamps stay as they are.
- PWA UI: the page explains the browser's permission step and, on iPhone,
  that the app must be on the home screen first. A test button sends one
  push to this device.
- API: `GET /api/v1/push/configuration` (public key, kinds),
  `PUT /api/v1/push/subscriptions`, `DELETE …/{id}`,
  `PUT /api/v1/push/preferences`, `POST /api/v1/push/test`.
- The specs that list push as a non-goal get a note pointing here.

## 11. Stages

Each stage is one PR, mergeable alone, with its switches off by default.

| Stage | Content | Depends on |
|---|---|---|
| 1 | §5.1 order number, §6.1, §6.2, §6.4 | – |
| 2 | §6.3 delivery-day mail | 1 |
| 3 | §5.2, §5.3, §7 cancellation invoice, ADR-0015 | – |
| 4 | §8.1 to §8.4, §8.7: capability, model, pledge, payments, admin UI, ADR-0016 | 3 |
| 5 | §8.5 donation receipt | 4 |
| 6 | §8.6 extra donation in the order forms | 1, 4 |
| 7 | §9 sponsor search | – |
| 8 | §10 push, ADR-0017 | – |

Tracks that run in parallel: mails (1, 2), invoices (3), search (7), push
(8). Donations (4, 5, 6) start when stage 3 is merged.

Rules for every stage:

- Tests first. Unit tests for domain rules; integration tests against real
  Postgres for transactions and scopes; a contract or stack proof for mail
  and documents; E2E only for behaviour that lives in the browser (form,
  permission prompt, palette target).
- Migrations start at 0062. A stage takes the next free number when it
  opens its PR and sets `down_revision` to the head of main; the lead
  resolves the order on merge.
- Agents do not edit gate files (OpenAPI approvals, network-fault manifest,
  vulnerability waivers). They report the need; the lead decides and logs
  it (E-045 and following).
- Help pages German first, then English, with revision fields; the known
  limits (`specs/leonaid-poc/KNOWN-LIMITS.md` and the docs page) change in
  the stage that lifts a limit.
- Texts with legal weight go into `legal-templates.ts` or the runbook as
  proposals marked "LEGAL REVIEW PENDING".

## 12. Decisions

**Mails**

- **D-M1 (lead).** Public-form mails stay unconditional. The switch covers
  internal orders and the delivery-day mail. Why: a buyer of the public
  form expects the confirmation; making it optional would be a regression.
- **D-M2 (lead).** A sweep enqueues the delivery-day mail; no future-dated
  jobs.
- **D-M3 (lead).** An internal order is confirmed when it becomes
  `review_ready`, once.
- **D-M4 (lead).** "Send again" needs no fresh login; it is audited and
  rate-limited.

**Cancellation invoice**

- **D-C1 (lead).** The cancellation invoice takes the next number of the
  invoice series. Why: one gapless series of outgoing invoice documents is
  the simplest to explain to an auditor; the document names the original.
  This closes the open point of ADR-0004 and ADR-0009.
- **D-C2 (lead).** One series per document kind and prefix for the
  installation (ADR-0015), replacing "per action and prefix".
- **D-C3 (lead).** Full cancellation only; payments of a cancelled paid
  invoice stay recorded until reversed; refunds stay outside LeonAid.
- **D-C4 (lead).** No documents are invented for old cancellations; a
  manager can issue them.

**Donations**

- **D-D1 (Björn).** Donations are a generic capability.
- **D-D2 (lead).** The second document of the order form is a donation
  pledge with a payment request, not an invoice. Why: an invoice implies
  something in return, which a donation must not have. Björn said "eine
  weitere Rechnung"; the document does that job under another name.
- **D-D3 (lead).** A receipt is issued only for a fully paid donation, one
  per donation, and can be voided, never edited.
- **D-D4 (lead).** The capability follows the existing lock; no exception
  for running actions.
- **D-D5 (lead).** The receiving body is configured once for the
  installation, separate from the invoice issuer, and may be another legal
  entity.
- **D-D6 (lead).** No donation without a configured receiving body.
- **D-D7 (lead).** One payment per donation; the receipt confirms what
  arrived, not what was pledged. Why: a receipt for a partial or split
  payment needs the collective form and a year boundary rule, which the
  first version does not have.
- **D-D8 (lead).** Receipts are signed by hand unless the club recorded the
  machine procedure. Why: an unsigned PDF by mail is only valid under that
  procedure. The dev tenant uses `machine` so the mail path can be tried.
- **D-D9 (lead).** No receipt from a notice older than § 63 Abs. 5 AO
  allows.

**Search**

- **D-S1 (lead).** The index holds name and city only.
- **D-S2 (lead).** Polling and a nightly pass, no Twenty webhook.

**Push**

- **D-P1 (lead).** Own Web Push implementation on existing dependencies.
- **D-P2 (lead).** No personal data of third persons in payloads.
- **D-P3 (lead).** Four kinds in the first version; each off until the user
  switches it on.

## 13. For Björn to sign

Nothing here blocks the build; each item blocks switching a feature on in
production.

- **P1.** The sentence about the legal basis for mails to buyers of internal
  orders, in the privacy notice.
- **P2.** The wording of the cancellation invoice.
- **P3.** The data of the receiving body, and the wording blocks of pledge
  and receipt (official sample; the tax adviser of the club should read
  them once).
- **P4.** The members' privacy paragraph on push (device tokens at Google,
  Apple, Mozilla, Microsoft).
- **P5.** Whether the prefix of the cancellation invoice shall differ from
  the invoice prefix after all (D-C1).
- **P6.** The sentence in the privacy notice that a donor's name and
  address go to the receiving body, when it is another legal entity than
  the club.

Björn, 2026-11-10: "lass dir passende Sätze für unseren Dev-Tenant
einfallen". Appendix A holds them. They are the values of the dev instance
and of the golden data ("Lions Club Musterstadt"), and the proposals a real
club starts from. They stay marked "LEGAL REVIEW PENDING" in
`legal-templates.ts`: a real club replaces P3 with its own data and has P1
to P4 read once.

## Appendix A: texts for the dev tenant

All data of the receiving body is synthetic.

### A.1 Privacy notice, mails for orders a member recorded (P1)

> **Bestellungen, die ein Mitglied für Sie erfasst**
> Nimmt ein Mitglied des Lions Club Musterstadt Ihre Bestellung persönlich
> oder am Telefon auf, speichern wir Ihren Namen, Ihre Liefer- und
> Rechnungsanschrift und Ihre E-Mail-Adresse, wenn Sie sie nennen oder sie
> uns aus einer früheren Bestellung vorliegt. An diese Adresse senden wir die Bestellbestätigung, am Liefertag einen Hinweis auf
> das Lieferfenster und, falls die Bestellung storniert wird, eine
> Stornobestätigung. Rechtsgrundlage ist die Erfüllung des Vertrags mit
> Ihnen (Art. 6 Abs. 1 Buchst. b DSGVO). Werbung senden wir an diese Adresse
> nicht.

Sentence in the confirmation mail of an internal order:

> Ihre Bestellung wurde von einem Mitglied des Lions Club Musterstadt für
> Sie erfasst. Stimmt etwas nicht, schreiben Sie uns bitte an
> kontakt@lions-musterstadt.example.

The mail names the club's address from the legal configuration and does not
ask for a reply: a reply address (`MAIL_REPLY_TO`) is optional and defaults
to a system address (ruling on the review of PR #216).

Delivery-day mail:

> Betreff: Ihre Lieferung kommt heute zwischen 10:00 und 12:00 Uhr
>
> Guten Morgen,
>
> Ihre Bestellung LA-7F3K2QWX vom Krapfentaxi 2026 wird heute, Samstag,
> 05.12.2026, zwischen 10:00 und 12:00 Uhr geliefert.
>
> Lieferadresse: …
> Bestellt: 2 Krapfenboxen (24 Stück)
>
> Ist in dieser Zeit niemand da, antworten Sie bitte auf diese E-Mail oder
> rufen Sie uns an: …

### A.2 Cancellation invoice (P2)

> **Stornorechnung KT26-0042**
> zur Rechnung KT26-0017 vom 28.11.2026
>
> Mit dieser Stornorechnung heben wir die Rechnung KT26-0017 vom 28.11.2026
> vollständig auf. Die Beträge der Rechnung werden mit umgekehrtem
> Vorzeichen ausgewiesen.

Closing line, invoice not paid:

> Aus der Rechnung KT26-0017 ist kein Betrag mehr zu zahlen.

Closing line, payments received:

> Auf die Rechnung KT26-0017 haben wir 72,00 € erhalten. Die Erstattung
> erfolgt gesondert.

Cover mail:

> Betreff: Stornorechnung KT26-0042 zur Rechnung KT26-0017 · Krapfentaxi 2026
>
> anbei erhalten Sie die Stornorechnung zu Ihrer Rechnung KT26-0017. Die
> Rechnung ist damit aufgehoben.

### A.3 Receiving body and donation texts (P3)

Receiving body of the dev tenant:

| Field | Value |
|---|---|
| Name | Förderverein Lions Club Musterstadt e. V. |
| Address | Marktplatz 1, 12345 Musterstadt |
| Tax office | Finanzamt Musterstadt |
| Tax number | 123/456/78901 |
| Notice | Freistellungsbescheid vom 15.03.2025 für den Veranlagungszeitraum 2021 bis 2023 |
| Purposes | Förderung der Jugendhilfe, der Bildung und mildtätiger Zwecke |
| Bank | Förderverein Lions Club Musterstadt e. V., IBAN DE02 1203 0000 0000 2020 51, BIC BYLADEM1001 (an example IBAN with a valid checksum; not the invoice account of the golden data, `DE89 3704 0044 0532 0130 00`) |
| Signatory | Erika Mustermann, Schatzmeisterin |
| Signing | `machine`, notified to the Finanzamt Musterstadt on 01.04.2025 |
| Prefixes | `SP26-` (pledge), `ZB26-` (receipt), width 4 |

Donation pledge:

> **Spendenzusage SP26-0001**
>
> Vielen Dank für Ihre Spende von 50,00 € für das Krapfentaxi 2026 des
> Lions Club Musterstadt. Der Erlös geht an die Jugendarbeit in
> Musterstadt.
>
> Bitte überweisen Sie den Betrag auf das Konto des Förderverein Lions Club
> Musterstadt e. V., IBAN …, und geben Sie als Verwendungszweck SP26-0001
> an.
>
> Ihre Spende ist freiwillig. Sie erhalten dafür keine Gegenleistung. Dieses
> Schreiben ist keine Rechnung. Nach Eingang Ihrer Zahlung senden wir Ihnen
> eine Zuwendungsbestätigung für Ihre Steuererklärung.

Sentence in the order form:

> Ihre Spende ist freiwillig und ohne Gegenleistung. Sie erhalten dafür eine
> eigene Zahlungsbitte, getrennt von der Rechnung für Ihre Bestellung, und
> nach Zahlungseingang eine Zuwendungsbestätigung.

Donation receipt, following the official sample for money donations (to be
compared with the current sample of the Federal Ministry of Finance before
a real club uses it):

> **Bestätigung über Geldzuwendungen**
> im Sinne des § 10b des Einkommensteuergesetzes an eine der in § 5 Abs. 1
> Nr. 9 des Körperschaftsteuergesetzes bezeichneten Körperschaften,
> Personenvereinigungen oder Vermögensmassen
>
> Name und Anschrift des Zuwendenden: …
> Betrag der Zuwendung in Ziffern: 50,00 € · in Buchstaben: fünfzig Euro
> Tag der Zuwendung: 09.12.2026
>
> Es handelt sich nicht um den Verzicht auf Erstattung von Aufwendungen.
>
> Wir sind wegen Förderung der Jugendhilfe, der Bildung und mildtätiger
> Zwecke nach dem Freistellungsbescheid des Finanzamtes Musterstadt,
> StNr. 123/456/78901, vom 15.03.2025 für den letzten Veranlagungszeitraum
> 2021 bis 2023 nach § 5 Abs. 1 Nr. 9 des Körperschaftsteuergesetzes von der
> Körperschaftsteuer und nach § 3 Nr. 6 des Gewerbesteuergesetzes von der
> Gewerbesteuer befreit.
>
> Es wird bestätigt, dass die Zuwendung nur zur Förderung der Jugendhilfe,
> der Bildung und mildtätiger Zwecke verwendet wird.
>
> Musterstadt, 10.12.2026 · Erika Mustermann, Schatzmeisterin
>
> Hinweis: Wer vorsätzlich oder grob fahrlässig eine unrichtige
> Zuwendungsbestätigung erstellt oder veranlasst, dass Zuwendungen nicht zu
> den in der Zuwendungsbestätigung angegebenen steuerbegünstigten Zwecken
> verwendet werden, haftet für die entgangene Steuer (§ 10b Abs. 4 EStG,
> § 9 Abs. 3 KStG, § 9 Nr. 5 GewStG). Diese Bestätigung wird nicht als
> Nachweis für die steuerliche Berücksichtigung der Zuwendung anerkannt,
> wenn das Datum des Freistellungsbescheides länger als 5 Jahre bzw. das
> Datum der Feststellung der Einhaltung der satzungsmäßigen Voraussetzungen
> nach § 60a Abs. 1 AO länger als 3 Jahre seit Ausstellung des Bescheides
> zurückliegt (§ 63 Abs. 5 AO).

With a notice after § 60a AO the paragraph "Wir sind wegen …" is replaced
by:

> Die Einhaltung der satzungsmäßigen Voraussetzungen nach den §§ 51, 59, 60
> und 61 AO wurde vom Finanzamt Musterstadt, StNr. 123/456/78901, mit
> Bescheid vom 15.03.2025 nach § 60a AO gesondert festgestellt. Wir fördern
> nach unserer Satzung die Jugendhilfe, die Bildung und mildtätige Zwecke.

Sentence under the signatory with `machine`:

> Diese Zuwendungsbestätigung wurde maschinell erstellt und trägt keine
> eigenhändige Unterschrift. Das Verfahren ist dem Finanzamt Musterstadt
> angezeigt (R 10b.1 Abs. 4 EStR).

Privacy notice, donations to another legal entity (P6):

> **Spenden**
> Spenden Sie im Rahmen einer Aktion, ist Empfänger Ihrer Spende der
> Förderverein Lions Club Musterstadt e. V. Wir übermitteln ihm dazu Ihren
> Namen, Ihre Anschrift, den Betrag und den Tag der Zahlung. Er stellt Ihnen
> die Zuwendungsbestätigung aus und bewahrt ein Doppel zehn Jahre auf
> (§ 50 Abs. 7 EStDV). Rechtsgrundlage ist die Erfüllung der
> Spendenvereinbarung mit Ihnen und die gesetzliche Aufbewahrungspflicht
> (Art. 6 Abs. 1 Buchst. b und c DSGVO).

### A.4 Members' privacy notice, push (P4)

> **Benachrichtigungen auf Ihrem Gerät**
> Schalten Sie in der App Benachrichtigungen ein, speichert LeonAid für Ihr
> Gerät eine Adresse des Benachrichtigungsdienstes Ihres Browsers oder
> Betriebssystems (Google, Apple, Mozilla oder Microsoft) und zwei
> Schlüssel. Über diesen Dienst senden wir verschlüsselte Hinweise, zum
> Beispiel „3 Wiedervorlagen sind fällig“. Die Hinweise enthalten keine
> Namen, Adressen oder Beträge. Der Dienst erfährt, dass und wann Ihr Gerät
> einen Hinweis von LeonAid erhält, aber nicht dessen Inhalt.
> Rechtsgrundlage ist Ihre Einwilligung (Art. 6 Abs. 1 Buchst. a DSGVO). Sie
> können sie jederzeit in der App unter „Benachrichtigungen“ widerrufen;
> LeonAid löscht die Adresse dann sofort. Sie wird auch gelöscht, wenn Sie
> sich auf dem Gerät abmelden oder der Dienst sie als ungültig meldet.
