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

A subscription is bound to the public key it was made with. Replacing the
key ends every subscription; members switch notifications on again.

### A device ends with its session

`push_subscription` holds, per device, the endpoint, the two keys of the
subscription and the browser identifier, and the session that registered
it. The row is deleted:

- when the member switches the device off;
- at once when the session is revoked (sign-out, revoked sessions, a
  suspended or erased account), by a database trigger, so no code path can
  forget it;
- within minutes after the session expired;
- when the push service answers 404 or 410.

After a new sign-in the app registers the device's subscription again.

### Kinds, consent and frequency

Four kinds: `follow_ups`, `feed`, `tasks`, `delivery`. Each is off until the
member switches it on (`push_preference`); switching is recorded as an audit
event (the consent and its withdrawal). A member is offered only the kinds
that can reach them. Nobody is told about their own action.

At most one push per member and kind in 15 minutes. Events within that time
are counted and sent together by one later job. `follow_ups` is asked for
once a day from 08:00 club time (not after 20:00) by a worker loop.

A push is a hint, not a delivery guarantee. A job is run again only when no
device of the member could be reached; it then sends the same count. A
device that was reached is not sent to twice on purpose.

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
- The members' privacy notice must describe the stored address, the keys,
  the browser identifier and the push services before the flag `pwa.push` is
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
