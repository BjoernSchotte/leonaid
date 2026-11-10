# ADR-0017: Web Push with an own implementation, a payload rule and an endpoint allowlist

- Status: accepted
- Date: 2026-11-10
- Deciders: the lead under the product owner's standing delegation (D-P1,
  D-P2, D-P3 of the spec) and the implementation
- Reference: `specs/mails-documents-donations-push/PLAN.md` §10

## Context

The acquisition app (PWA) sent no push notifications: follow-ups, new orders
in "Neues", assigned tasks and assigned deliveries were visible only to a
member who opened the app.

Web Push needs three things on the server: message encryption (RFC 8291,
content coding `aes128gcm` of RFC 8188), application server identification
(VAPID, RFC 8292) and an HTTP request to the push service of the browser
vendor. The usual Python library for this, `pywebpush`, is not installed. It
brings `py-vapid` and `http-ece` with it and sends with `requests`, which
LeonAid does not use directly. `cryptography` and `httpx` are direct
dependencies already. Every dependency is pinned, scanned and updated
(`infra/locks/README.md`), so three more packages are a standing cost.

Two facts shape the rest:

- A push passes through a service of Google, Apple, Mozilla or Microsoft.
  The body is encrypted for the device, but the push service sees that and
  when a device gets a message, and the notification text ends up on a lock
  screen.
- The endpoint of a subscription comes from the member's browser. It is
  input. A worker that posts to any URL a browser names can be made to call
  hosts inside the installation.

## Decision

### Own implementation on `cryptography` and `httpx`

`leonaid.adapters.web_push` implements the sender:

- `encrypt_push_message`: one `aes128gcm` record per message with a fresh
  P-256 sender key and a fresh salt (RFC 8291 section 3.4), record size
  4096, no padding beyond the delimiter.
- `VapidSigner`: an ES256 JWT with `aud` (origin of the push resource),
  `exp` (12 hours) and `sub`, in the `vapid t=…, k=…` scheme of RFC 8292.
- `WebPushSender`: one POST per subscription with `TTL: 86400`,
  `Urgency: normal` and `Topic: <kind>`, so a push service keeps at most one
  undelivered message per kind for a device that is off.

The encryption is pinned by the example of RFC 8291 section 5 (the test
reproduces the RFC's body byte for byte from its keys and salt). The JWT is
checked with a signature verification. An integration proof sends through
the worker job to a local HTTP receiver that verifies the VAPID token and
decrypts the body with the subscription's private key, written from the
RFC's receiver side and independent of the sender.

No Python or JavaScript dependency is added.

### Payload rule

A push carries exactly three values: `kind`, `count` and `path`
(`leonaid.domain.push.PushMessage`). The notification text is written on the
device by the service worker from the kind and the count ("3 Wiedervorlagen
sind fällig."). No name, address, amount or record id is sent, also not
encrypted. The job that asks for a push (`push.notification.v1`) carries a
member, a kind and a count, nothing about the record that caused it.

The service worker shows a notification for every push, also for one it
cannot read: browsers end subscriptions whose pushes stay silent. It follows
only target paths below the PWA base.

### Endpoint allowlist

LeonAid sends only to the push services of the browser vendors
(`leonaid.domain.push.PushEndpointPolicy`): `fcm.googleapis.com` and
`jmt17.google.com` (Chrome and other Chromium browsers),
`updates.push.services.mozilla.com` (Firefox), `web.push.apple.com` (Safari
and home-screen web apps on iPhone and iPad) and hosts below
`notify.windows.com` (Edge on Windows). The scheme is `https`, the port the
default one, and a URL with credentials or a fragment is refused.

The rule is checked twice: when a member registers a device, and again
before every request, because a stored row is no proof of where it points.
The HTTP client follows no redirect and reads no proxy setting from the
environment. A new push service needs a code change and a release.

For proofs the policy takes extra whole origins (scheme, host, port). The
composition of the API and the worker passes none, and no environment
variable can add one.

### Keys

One VAPID key pair per installation. `LEONAID_VAPID_PRIVATE_KEY` is the
base64url of the 32-octet P-256 private scalar, created by
`./leonaid bootstrap` and by `./leonaid pilot-secrets`.
`LEONAID_VAPID_SUBJECT` is the operator's contact (`mailto:` or `https:`)
that the push services read from every push; production refuses reserved
names such as `example.org` and `.invalid`. The API publishes the public
half; the worker signs. Both get the same values (deployment contract and
pilot doctor). Without the key the feature is "not configured": the API
says so, and the worker sends nothing.

A subscription is bound to the public key it was made with, and each row
stores that key. After the key was replaced, the old subscriptions are dead:
the worker sends only to rows of the current key and deletes the others;
the API refuses a subscription whose browser names another key; the app
compares the key at start and on the page, ends the old subscription and
subscribes again with the current key (the permission is still granted, so
the browser does not ask). The page never shows a dead subscription as
switched on.

### A device ends with its session

`push_subscription` holds, per device, the endpoint, the two keys of the
subscription, the VAPID key it was made with and the session that
registered it. Nothing about the browser is stored (no user agent). A member
has at most 10 devices. The row is deleted:

- when the member switches the device off;
- at once when the session is revoked (sign-out, revoked sessions, a
  suspended or erased account), by a database trigger, so no code path can
  forget it;
- within minutes after the session expired;
- when the push service answers 404 or 410;
- when the push service did not take 5 messages in a row for it, on at
  least 3 different club days, the first at least 3 days ago
  (`failure_count`, `failure_days`, `failing_since`; a delivery resets
  them). Only a refusal of the push service counts (a 4xx other than 429).
  No answer at all (no route, DNS, timeout) and an answer of 429 or 5xx are
  logged and not counted: they say how the network or the service is, not
  the device, so no outage removes a device;
- when it was made with another VAPID key than the current one.

One endpoint is one row. A member may renew the keys of their own row. A
row of another member moves to the caller only when the submitted keys
(`p256dh`, `auth`) equal the stored ones: then it is the same browser
subscription, a shared device on which another member signed in, and the
new member's consent is recorded. With other keys the API answers 409
`push_device_bound` and changes nothing: knowing an endpoint URL is no way
to take over or silence another member's device. The rule is the `WHERE` of
the upsert itself, so it also holds for two members who send one new
endpoint at the same moment. No API response carries an endpoint or keys.

Ownership of an endpoint is first come. When the owner's row is gone
(session ended, removed after failures, key replaced), someone who knows
the endpoint could register it first. The owner's browser then gets 409 for
its own subscription; the app ends that subscription, subscribes again (a
new endpoint) and registers that. A message appears only if this fails
too.

After a sign-out the browser's subscription is gone too: the member
switches the device on again after the next sign-in. A session that ended
without a sign-out leaves the browser's subscription; the app registers it
again at its next start. A session lasts 90 days, so a device whose app was
not opened for that long gets no push until it is opened again.

### Kinds, consent and frequency

Four kinds: `follow_ups`, `feed`, `tasks`, `delivery`. Each is off until the
member switches it on (`push_preference`); switching is recorded as an audit
event (the consent and its withdrawal). A member is offered only the kinds
that can reach them. Nobody is told about their own action.

At most one push per member and kind in 15 minutes. Events within that time
are counted and sent together by one later job. `follow_ups` is asked for
once a day from 08:00 club time (not after 20:00) by a worker loop.

### A push never fails a job and never pages an operator

A push is a hint, not a delivery guarantee. The job sends to all devices of
the member at once and ends by itself after 15 seconds; one request ends
after 10 seconds as a whole. Mail and document jobs wait behind it for
seconds.

The job does not fail because a device or a push service was not reached
(timeout, 429, 5xx). It ends, and one later job tries the devices not
reached yet, after 1 minute and again after 10 minutes. After the third try
the message is given up; it is logged, not counted on the device. So an
outage of a push service or of the network produces no dead letter and no
alert, and a member's own subscription plus "Test senden" cannot produce
one either. A device that got the message is marked with the job's id: the
same job run again by the outbox skips it, so nobody gets a message twice.

An answer of 400, 401, 403 or 413 means the push service refuses the
message (a wrong VAPID key or subject, a malformed request). It is not
tried again and counts as a failure on the device.

Every message that did not reach a device is one log line
`worker.push.undelivered` with the kind, the push service's name, the HTTP
status (empty when nobody answered), the try and whether the device was
removed. The name is the listed host, or `notify.windows.com` for every host
below it: the labels below that suffix are chosen by the member's browser
and are not logged. The path of an endpoint is the device's token and is
never logged, nor is the member.

### Limits per member

Registering a device (30 per hour) and the test push (5 per 10 minutes) are
counted per member, not per address, User-Agent or session: each is a
request that costs the installation something at a browser vendor.

## Consequences

- LeonAid maintains about 250 lines of protocol code. The RFC vector and the
  receiver proof catch a regression; a change of the Web Push protocol
  itself would need work here instead of a library update.
- Delivery through FCM, Mozilla autopush, APNs and WNS cannot be proven in
  the test stacks, which have no route to them. It is checked by hand on
  real devices before the flag is switched on.
- Notification texts are fixed in the service worker. A text change ships
  with a PWA release, and an installed app shows the old text until it has
  updated.
- The members' privacy notice must describe the stored address, the keys
  and the push services before the flag `pwa.push` is
  switched on (spec §13, P4).
- Not part of this decision: push in the web admin, notification actions,
  badges, per-device preferences, quiet hours chosen by the member.

## Alternatives rejected

- **`pywebpush`**: three new packages and a second HTTP client for code that
  fits on a few pages and is pinned by an RFC vector.
- **A hosted notification service**: device tokens and the fact of every
  push would go to one more company.
- **Texts in the payload**: simpler worker and service worker, but names of
  sponsors and buyers would reach lock screens and, encrypted, the push
  services.
