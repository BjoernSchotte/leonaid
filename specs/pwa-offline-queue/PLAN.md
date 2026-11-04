# Offline capture queue in the acquisition PWA

Status: 2026-11-04. Specification for review. Nothing in this document is
implemented. Björn decided on 2026-11-03 that the PWA gets an offline capture
queue; this document says how. The open questions are in [§17](#17-open-questions-for-björn);
implementation needs a separate go per stage (§16).

Code references are to `feat/leitsystem` at f58fbb08 (the Leitsystem PWA shell,
6.2 delivery board, 6.5 "ausgebucht"), which is ahead of `main` for every file
named here. All paths are relative to the repository root.

## 1. Context

Acquirers work on the move: at the sponsor's door, in a basement shop, at a
fair hall with no signal. Today the PWA tells them the truth: nothing is
saved offline.

- The offline banner (`packages/ui/src/components/mobile-shell.tsx:79`):
  "Du bist offline. Geöffnete Inhalte bleiben sichtbar. LeonAid speichert
  keine Änderungen im Hintergrund."
- The offline page the service worker serves for a navigation without network
  (`apps/pwa/public/offline.html`): "LeonAid speichert bewusst keine Formulare
  offline. Stelle die Verbindung wieder her und lade den Arbeitsbereich neu; so
  entstehen keine doppelten Aktivitäten oder Bestellungen."
- Mutations fail at once offline (`apps/pwa/src/main.tsx`,
  `mutations: { networkMode: "always", retry: false }`), so a form keeps its
  input and the acquirer retries by hand.

The Leitsystem prototype promised more: "Du bist offline. Eingaben werden
gespeichert und gesendet, sobald du wieder online bist. _N_ wartet." with a
badge "Wartet auf Verbindung" on a contact entry and "Bestellung gespeichert …
Wird gesendet, sobald du wieder online bist." on an order
(`.local/design-next/prototype/src/pages/pwa/Acquire.tsx:99-103, 400, 533-538`).
The prototype queue is an in-memory array that empties itself; it has no
idempotency, conflicts or storage. Björn's decision (memory
`pwa-offline-queue`, 2026-11-03): acquirers must be able to record captures
offline; they are queued and sent automatically when the device is back
online. No command palette in the PWA.

## 2. Goals

1. G1: An acquirer can record a contact attempt (with or without a follow-up)
   and an order for one of their sponsors without network. The entry is kept
   on the device and sent when the network returns, without a second tap.
2. G2: Every queued entry reaches Core **at most once**, also when the answer
   to a send is lost, the app is closed mid-send, or two tabs are open.
3. G3: Nothing queued is changed silently. When the server state moved on (a
   colleague's contact, a retired or full delivery window, a new price, a
   suppressed channel), the acquirer decides, in plain "Du" German, with the
   entry's content kept.
4. G4: The device holds as little personal data as the job needs, for as short
   as possible, and loses it on sign-out, account switch and expiry.
5. G5: The behaviour is the same on Android and iOS, where iOS has no
   background sync: sending happens when the app is opened, focused or comes
   back online while open.
6. G6: Everything that is online-only today stays online-only, visibly.

## 3. Non-goals

- Offline administration (the back office `apps/web` stays online-only).
- Offline reading of everything. Only what a queued capture needs is cached
  (§8.2).
- Offline sponsor **creation** that writes to the CRM without the acquirer's
  match decision. A new sponsor can be drafted offline but is resolved online
  (§6, §10.4).
- Offline delivery board for drivers. The driver view keeps its no-store rule
  (§14.3).
- Background Sync on iOS, push notifications, periodic sync.
- Conflict-free replicated data types or merging of free text. Conflicts are
  resolved by the acquirer, one entry at a time.
- Offline payments, invoices, exports or anything behind a fresh-login
  step-up (§6.2).

## 4. Terms

| Term          | Meaning                                                                                                                                                                 |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| capture       | One thing the acquirer records: a contact attempt (activity), a follow-up (part of an activity), an order (commitment), a sponsor draft.                                |
| queue entry   | A capture stored on the device until Core accepted it. It holds the request body, its idempotency key, the base data it was made against, and its state (§9.3).         |
| base snapshot | The values the capture was made against: assignment revision, offering price, delivery window and its "ausgebucht" flag, the time of capture. Used to detect conflicts. |
| read cache    | The minimal server data the PWA keeps on the device so that captures can be made offline: the acquirer's sponsor list and the order capture context (§8.2).             |
| send          | One HTTP attempt to deliver a queue entry. A send may be repeated with the same key.                                                                                    |
| conflict      | Core refused an entry for a reason the acquirer must decide (§10). Not a transient failure.                                                                             |
| captured at   | The device time when the acquirer saved the capture. Untrusted; bounded by the server (§11.2).                                                                          |

## 5. Summary of the proposal

- **What queues:** contact attempts with optional follow-up, and orders
  (internal capture, `source: acquisition`), each for a sponsor already in the
  acquirer's list. New sponsors can be **drafted** offline and are resolved
  online with the existing match step (§6).
- **The app must start offline.** The service worker serves the cached app
  shell instead of `offline.html` for `/app/` navigations (§8.1), and the PWA
  keeps a small encrypted read cache of the sponsor list and the capture
  context.
- **Storage:** one IndexedDB database per signed-in user, three stores (queue,
  read cache, meta). Every record is AES-GCM encrypted with a non-extractable
  WebCrypto key held in the same database (§8.3). Retention: queued entries 14
  days, read cache 7 days, everything cleared on sign-out, account switch and
  session expiry.
- **Sync:** sequential per sponsor, in capture order, with one per-entry
  idempotency key (`Idempotency-Key` header, the pattern Core already uses),
  exponential backoff for transient failures, a Web Lock so only one tab sends,
  triggered by `online`, app open, `visibilitychange` and a manual "Jetzt senden".
- **Server changes:** idempotency for `recordAcquisitionActivity` (it has none
  today), a bounded `capturedAt` on activities and acquisition orders, a price
  guard for offline orders, and activity recording that keeps the contact even
  when the assignment changed meanwhile (§11). Day rules go through
  `leonaid.domain.calendar.local_day`.
- **UX:** new banner copy, a queue indicator in the PWA bar, a "Warteschlange"
  sheet with per-entry status and resolution, a sign-out warning (§12).
- **Effort:** about 12–15 days in four stages (§16).

## 6. Scope: what queues and what stays online

### 6.1 Queued

| Capture                                            | Today (PWA)                                                                                       | Endpoint                                                                         | Idempotency today                                                | Offline                                                                 |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Contact attempt (channel, outcome, note)           | `ActivityWorkspace` (`packages/features/src/acquisition/activity-workspace.tsx`)                  | `POST /api/v1/actions/{id}/acquisition/activities` (`recordAcquisitionActivity`) | **none**; optimistic `revision` (`assignment_revision_conflict`) | **queue**                                                               |
| Follow-up (next action + due date)                 | same form, `next_action` + `due_on`                                                               | same                                                                             | same                                                             | **queue** (part of the activity)                                        |
| Order (acquisition capture, draft or review-ready) | `CommitmentCapturePage` (`packages/features/src/commitments/commitment-capture.tsx`)              | `POST …/commitments` (`createCommitment`)                                        | `Idempotency-Key` + request hash (`command_receipt`)             | **queue**                                                               |
| Completing an own draft (delivery details)         | `CompleteDraft` (`complete-draft.tsx`)                                                            | `POST …/commitments/{id}/complete`                                               | `Idempotency-Key`                                                | **queue**, only for drafts already on the server                        |
| New sponsor                                        | `SponsorWorkspace` "Neu" (`sponsor-workspace.tsx`: `previewSponsorMatch` → `resolveSponsorMatch`) | `POST …/acquisition/sponsor-match`, `…/sponsor-match/resolve`                    | `command_id` on resolve                                          | **draft only**: saved on the device, the match step runs online (§10.4) |

A capture for a queued sponsor draft (for example, a contact attempt for a
company met at a fair) is queued with a dependency on the draft and sent after
the draft was resolved (§9.2).

### 6.2 Stays online

| Area                                                                                                                                           | Why                                                                                                                     |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Sign-in, invitation, email change, `/fresh-login`                                                                                              | They are the trust anchor; nothing to queue.                                                                            |
| Anything behind `authenticate_fresh` (38 routes in `routes.py`: exports, member and role administration, legal configuration, invoice issuing) | A step-up proves presence _now_. A queued step-up is a contradiction. None of it is in the PWA today.                   |
| Payments, invoices, cancellations                                                                                                              | Back office only; money must not move on stale data.                                                                    |
| Delivery board (driver ticks, closing windows)                                                                                                 | No-store rule for addresses and phones (§14.3); the board hides itself offline (`hideOffline` in `delivery-board.tsx`). |
| Sponsor match decision (`resolveSponsorMatch`)                                                                                                 | It reads the CRM (Twenty) live and may create a CRM record; the acquirer must see the candidates.                       |
| Tasks, materials, knowledge, inbox modules                                                                                                     | Shared editing with revisions; out of scope for the first version (Q7).                                                 |
| Assignment changes (status, priority without a contact)                                                                                        | Not a PWA function today.                                                                                               |

## 7. What exists today

- **Service worker** (`apps/pwa/public/sw.js`): precaches the app shell and
  build assets; for a `/app/` navigation without network it returns
  `offline.html`, so **the app itself does not start offline**. API responses
  are never cached by the service worker.
- **Query client** (`apps/pwa/src/main.tsx`): in-memory TanStack Query, no
  persistence; mutations fail at once offline.
- **Online state** (`apps/pwa/src/app.tsx:100-154`): `online`/`offline`
  window events drive the shell banner and the gold network glyph.
- **Idempotency:** `command_receipt(idempotency_key, command_type,
request_hash, result, completed_at)` with the per-key advisory lock pattern
  (`adapters/postgres/commitments.py` `_create_once`, `_complete_once`;
  `adapters/postgres/acquisition.py` for the sponsor resolution). Keys match
  `^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$` (`application/commitments.py:32`). A
  refused command rolls back its receipt, so the same key can be resent after a
  4xx (proven for "ausgebucht" in KLF-065, `tools/delivery/fully_booked.py`).
  Receipts are never deleted today (no retention job touches
  `command_receipt`).
- **Activities** (`application/activities.py` `ActivityManagementService.record`):
  `occurred_at` is the server time; the expected revision must equal the
  assignment's revision; email/phone attempts are refused for suppressed
  channels (`contact_suppressed`); `due_on` becomes 09:00 in the club's zone.
- **Orders** (`application/commitments.py`, `adapters/postgres/commitments.py`):
  server pricing; the client quote (`quotedUnitPriceMinor`) is ignored for
  internal capture ("Der Core übernimmt beim Speichern den aktuellen
  Angebotspreis"); delivery windows are validated at send time
  (`delivery_window_unavailable`, `delivery_window_full` with
  `allowFullWindow`).
- **Sessions:** 90 days (`domain/sessions.py` `SESSION_LIFETIME`), HttpOnly
  `__Host-` cookie; a 401 means sign in again.
- **CSP:** `connect-src 'self'`, `script-src 'self'`, no inline code
  (`infra/proxy/Caddyfile`). WebCrypto and IndexedDB need nothing extra.
- **Tests:** `tests/e2e/pwa-audit.spec.mjs` uses `context.setOffline(true)` to
  check the banner and that a form keeps its input.

## 8. Storage

### 8.1 Starting offline

The service worker answers a `/app/` navigation without network with the
cached `/app/` shell (index.html of the current build) instead of
`offline.html`. `offline.html` stays for the first visit before the shell was
cached and for paths the PWA does not know. The shell then starts, reads the
user and the read cache from IndexedDB (§8.2) and shows the offline banner.

Identity offline: the PWA keeps the last `getCurrentIdentity` answer in the
meta store (user id, display name, memberships for acquisition). It is only
used to render the shell and to bind the queue to the user; Core checks the
session and membership again at every send.

### 8.2 Read cache (minimal)

| Data                             | Fields kept                                                                                                                                                                                                  | Source                        | Why                                                                                             |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------- | ----------------------------------------------------------------------------------------------- |
| Sponsor list per action          | `assignmentId`, `partyKind`, `partyId`, `partyDisplayName`, `city`, `status`, `nextAction`, `dueAt`, `revision`, `suppressedChannels`; **plus** `phone` and `contactName` if Q2 says yes                     | `getAcquisitionActivityBoard` | pick the sponsor, show the follow-up, base revision, refuse suppressed channels already offline |
| Order capture context per action | offerings (`id`, `name`, `unit`, `unitPriceMinor`, `currency`, `allowedQuantityUnits`, `piecesPerUnit`, availability), delivery configuration (`enabled`, `timezone`, windows with `fullyBooked`, `retired`) | `getCommitmentCaptureContext` | price preview, unit choice, window choice                                                       |
| Identity summary                 | user id, display name, action ids and names with the acquirer role                                                                                                                                           | `getCurrentIdentity`          | shell and queue binding                                                                         |

Not cached: email addresses, postal addresses of sponsors, invoice recipients
of earlier orders, other acquirers' names, the activity feed, the dashboard,
delivery board data, documents.

The read cache is refreshed whenever the PWA is online and the page is visible
(on open, focus and after each successful send), and replaced as a whole per
action. Entries older than 7 days are not shown; the app then says
"Deine Sponsorenliste ist älter als 7 Tage. Geh online, um sie zu
aktualisieren." and offline capture is blocked until it is refreshed (Q3).

### 8.3 IndexedDB layout

One database per user: `leonaid-pwa-v1-<userId>`. Object stores:

| Store   | Key              | Value (encrypted)                                                             | Indexes (clear text)                                             |
| ------- | ---------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `queue` | `entryId` (UUID) | the queue entry (§9.3)                                                        | `state`, `actionId`, `sequence` (monotonic integer), `dependsOn` |
| `cache` | `kind:actionId`  | the read-cache document and its `fetchedAt`                                   | `fetchedAt`                                                      |
| `meta`  | fixed keys       | identity summary, schema version, last sync result, the encryption key handle | —                                                                |

Index values are not personal data (ids, states, numbers). The database name
contains the user id, not the email address.

A small unencrypted record in `localStorage` (`leonaid-pwa-active-user`) names
the user whose database is current; it holds the user id only.

### 8.4 Encryption at rest

Threat model: a **lost or stolen phone**, and a browser profile copied or
synced to another machine. Not in scope: malware on the unlocked device, a
person using the unlocked phone with the PWA open.

- Android and iOS encrypt their storage when the device is locked (file-based
  encryption, Data Protection). That is the main protection for a lost, locked
  phone, and the spec relies on it.
- In addition, every IndexedDB value is encrypted with AES-GCM-256 using a
  WebCrypto key generated with `extractable: false` and stored as a
  `CryptoKey` in the `meta` store. The key never exists as bytes in
  JavaScript. This protects against copying the IndexedDB files (backups,
  forensic image of an unlocked device's app container, a desktop profile
  copy): the copy is useless without the browser's key store. It does **not**
  protect against code running in the page; that is what CSP and the absence
  of third-party scripts do.
- A user-entered PIN for the queue (key derived with PBKDF2) is rejected: it
  adds a second login for little gain, and a forgotten PIN loses captures
  (Q4).
- A server-wrapped key (fetched at sign-in, kept only in memory) is rejected:
  after an app restart offline the queue could not be read, which defeats the
  purpose.

### 8.5 Retention and clearing

| Event                                                      | Effect                                                                                                                                                                |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Entry accepted by Core                                     | removed from `queue` at once; the shell shows "Gesendet" for this session only (memory)                                                                               |
| Entry discarded by the acquirer                            | removed at once                                                                                                                                                       |
| Entry older than 14 days (by `capturedAt`)                 | state "Abgelaufen"; kept 2 more days with a visible warning, then deleted (Q5)                                                                                        |
| Read cache older than 7 days                               | not shown; deleted after 14 days                                                                                                                                      |
| Sign-out (`/logout` from the PWA)                          | if the queue is not empty: warning dialog with the count (§12.5); then the user's database is deleted (`indexedDB.deleteDatabase`) and the active-user record removed |
| Session expired (401)                                      | queue is **kept** and paused; banner "Melde dich wieder an, damit LeonAid … senden kann"; after sign-in as the **same** user it resumes                               |
| Sign-in as another user on the device                      | the other user's database is deleted before the new user's shell renders; nothing of it is shown or sent (Q6)                                                         |
| Membership ended or acquisition switched off (403 on send) | entries for that action go to "Nicht mehr möglich"; the acquirer can read and discard them; deleted after 2 days                                                      |
| App uninstall / site data cleared                          | everything is gone; Core has only what was sent                                                                                                                       |

The PWA calls `navigator.storage.persist()` after the first queued entry, so
that the browser does not evict the database under storage pressure. A
refused request is not an error; the queue indicator then says "Gerät kann
Einträge löschen, wenn der Speicher knapp wird" in the sheet.

## 9. Sync

### 9.1 Triggers

There is no Background Sync on iOS, and the spec does not use it on Android
either (one behaviour, G5). The sync loop runs in the page:

- on app start, when a user and a non-empty queue exist;
- on the `online` event;
- on `visibilitychange` to visible and on `focus`;
- after each new queue entry while online (immediate send);
- on "Jetzt senden" in the queue sheet;
- on a backoff timer while the page is visible.

A Web Lock (`navigator.locks.request("leonaid-sync-<userId>")`) makes sure only
one tab sends; other tabs follow the state through a `BroadcastChannel`. A
capture made while online goes through the same queue (write, then send at
once), so there is one code path, and a lost answer while "online" is handled
like any other (G2).

### 9.2 Ordering and dependencies

- Entries are sent in `sequence` order **per sponsor** (`partyKind:partyId`),
  one at a time. Different sponsors are independent, but the loop still sends
  sequentially (small queues, simple reasoning, no request bursts against the
  rate-sensitive CRM).
- An entry that waits for a conflict decision blocks only later entries for
  the same sponsor. Example: contact attempt → order; if the contact attempt
  hits a conflict, the order waits.
- An entry with `dependsOn` (capture for a sponsor draft) waits until the
  draft was resolved and then takes the resolved `partyKind`/`partyId` and the
  new assignment revision.
- Two follow-ups for the same sponsor offline: both are sent in order; the
  second is based on the revision the first one produced (the loop updates the
  base revision of later entries from each accepted answer).

### 9.3 Queue entry

```json
{
  "entryId": "0f8c…",
  "sequence": 42,
  "kind": "activity | commitment | commitment-completion | sponsor-draft",
  "actionId": "2000…",
  "party": { "kind": "company", "id": "4000…" },
  "dependsOn": null,
  "idempotencyKey": "pwa-q:0f8c…",
  "capturedAt": "2026-11-04T09:12:30.512+01:00",
  "base": {
    "assignmentRevision": 7,
    "unitPriceMinor": 3600,
    "windowId": "…",
    "windowFullyBooked": false
  },
  "request": { "…": "the exact API body" },
  "state": "queued | sending | conflict | failed | expired | blocked",
  "attempts": 3,
  "nextAttemptAt": "…",
  "lastError": { "code": "assignment_revision_conflict", "status": 409 }
}
```

The key is created once, when the capture is saved, and never changes. The
request body is frozen at save time; a resolution that changes content (another
window, a confirmed new price) creates a new body **and a new key**, because
the content hash changes (Core would answer `idempotency_conflict` otherwise).
The entry keeps a link to the old key for support.

### 9.4 Results and retry

| Answer                                     | Meaning                               | Action                                                                   |
| ------------------------------------------ | ------------------------------------- | ------------------------------------------------------------------------ |
| 2xx (also `replayed: true`)                | accepted                              | remove entry; update read cache and later entries' base revision         |
| network error, timeout (15 s), 502/503/504 | transient                             | backoff                                                                  |
| 429                                        | rate limited                          | backoff, at least `Retry-After`                                          |
| 409 `idempotency_incomplete`               | another send with this key is running | backoff                                                                  |
| 401                                        | session gone                          | pause the whole queue; ask to sign in                                    |
| 403                                        | no longer allowed                     | entries of that action → "Nicht mehr möglich"                            |
| 404 (concealed resource)                   | sponsor no longer assigned            | entry → conflict "Sponsor nicht mehr in deiner Liste"                    |
| 409/422 with a known code                  | conflict                              | entry → "Braucht deine Entscheidung" (§10)                               |
| 409 `idempotency_conflict`                 | same key, other content: a bug        | entry → "Fehlgeschlagen", support code shown, never resent automatically |
| other 4xx/5xx                              | unknown                               | after 5 attempts → "Fehlgeschlagen" with "Erneut versuchen"              |

Backoff: 2 s, 4 s, 8 s … capped at 5 minutes, with ±20 % jitter, only while the
page is visible; reset on `online` and on "Jetzt senden".

## 10. Conflicts and their resolution (in "Du")

Each conflict opens in the queue sheet with the entry's content, the reason and
the choices. Nothing is resent without the acquirer's choice, except where the
table says "automatisch".

### 10.1 Contact attempts and follow-ups

| Server answer                                                                                                                                         | What the acquirer sees                                                                                                                                                | Choices                                                                                           |
| ----------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| assignment changed meanwhile (`assignment_revision_conflict`; with the server change in §11.4 the contact is kept and only the follow-up is reported) | "Dein Kontakt mit _Bäckerei Kern_ ist gespeichert. Die Wiedervorlage wurde nicht übernommen, weil _Tom_ inzwischen etwas eingetragen hat: _Angebot schicken, 12.11._" | **Meine Wiedervorlage übernehmen** (new send with the current revision) · **Seine/Ihre behalten** |
| `contact_suppressed`                                                                                                                                  | "_Bäckerei Kern_ möchte nicht per E-Mail kontaktiert werden. Der Kontakt wurde nicht gespeichert."                                                                    | **Als Besuch speichern** (channel changed, new key) · **Verwerfen**                               |
| sponsor no longer assigned (404)                                                                                                                      | "_Bäckerei Kern_ ist dir nicht mehr zugeordnet. Der Eintrag kann nicht gesendet werden."                                                                              | **Notiz kopieren** · **Verwerfen**                                                                |
| assignment handed over                                                                                                                                | same as above, "… wurde übergeben"                                                                                                                                    | same                                                                                              |

### 10.2 Orders

| Server answer                                              | What the acquirer sees                                                                       | Choices                                                                                                                                    |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `delivery_window_full`                                     | "Das Lieferfenster _Do 12.11., 08–10 Uhr_ ist inzwischen ausgebucht."                        | **Trotzdem eintragen** (`allowFullWindow`, same key: the flag is not in the hash) · **Anderes Fenster wählen** · **Als Entwurf speichern** |
| `delivery_window_unavailable` (retired or started)         | "Das Lieferfenster _…_ gibt es nicht mehr."                                                  | **Anderes Fenster wählen** · **Als Entwurf speichern**                                                                                     |
| `commitment_price_changed` (new, §11.3)                    | "Der Preis für _Krapfenbox_ ist jetzt 38,00 € statt 36,00 €. Die Bestellung kostet 76,00 €." | **Neuen Preis übernehmen** · **Verwerfen**                                                                                                 |
| `offering_not_available`                                   | "_Krapfenbox_ ist nicht mehr bestellbar."                                                    | **Verwerfen**                                                                                                                              |
| `commitment_ordering_disabled`, `commitment_action_closed` | "Für _Krapfentaxi 2026_ nimmt der Club keine Bestellungen mehr an."                          | **Verwerfen** (the content stays readable for 2 days)                                                                                      |
| `delivery_required` (delivery switched on meanwhile)       | "Für diese Aktion braucht eine Bestellung jetzt eine Lieferadresse und ein Lieferfenster."   | **Ergänzen** · **Als Entwurf speichern**                                                                                                   |

"Als Entwurf speichern" sends the same capture with `readyForReview: false`,
which skips delivery validation and the window guard (draft creation is not
checked, the task 6.5 rule); the acquirer completes it later online.

### 10.3 Automatic resolutions

- A replay (`replayed: true`) is success.
- Base revision moved because an **own** earlier queue entry was accepted:
  the loop updates the base before sending (§9.2); no conflict.
- Read cache refresh shows a window as full before the send: the entry is
  marked "Braucht deine Entscheidung" before it is sent at all (no 409 round
  trip).

### 10.4 Sponsor drafts

A sponsor draft never sends itself. When online, the queue sheet shows "Neuer
Sponsor _Fa. Muster_ wartet auf deine Prüfung" and opens the existing match
step (`previewSponsorMatch`, then `resolveSponsorMatch` with the draft's
`command_id`). Entries that depend on the draft are sent after the
resolution. A draft can be discarded; dependent entries are then discarded
too, after a confirmation that names them.

## 11. Server changes

### 11.1 Idempotency for activities

`POST /api/v1/actions/{id}/acquisition/activities` accepts an `Idempotency-Key`
header and stores a `command_receipt` (`command_type =
"acquisition.activity.record"`, request hash over party, channel, outcome,
note, next action, due date, captured at, base revision) like
`createCommitment`. The key is **required** for new clients (422
`idempotency_key_required` when missing) after one release in which it is
optional, so an older cached PWA keeps working during the update. The result
stores the activity id; a replay returns the stored activity and assignment.

### 11.2 Captured at

- Optional `capturedAt` (ISO 8601 with offset) on `RecordAcquisitionActivityRequest`,
  `CreateCommitmentRequest` (acquisition source only) and
  `CompleteCommitmentRequest`.
- Bounds: not later than server now + 5 minutes; not earlier than server now −
  14 days (the queue's retention, §8.5); outside → 422
  `captured_at_out_of_range` (the queue shows "Die Uhrzeit deines Geräts
  stimmt nicht. Prüfe Datum und Uhrzeit."). The device clock is untrusted;
  the bounds keep a wrong clock from writing history far away.
- Activities: `occurred_at` = `capturedAt` (the contact happened then);
  `created_at` becomes the server receive time. Today
  `record_activity` (`adapters/postgres/acquisition.py`) writes `created_at`
  from the same `occurred_at` value; with `capturedAt` the two split, so no
  new column is needed.
- Orders: new nullable `commitment.captured_at`, shown in the order detail
  ("Erfasst offline am 04.11. um 09:12"); `created_at` stays the server time
  and keeps driving lists, the weekly value and invoices.
- Every day rule that reads one of these instants uses
  `leonaid.domain.calendar.local_day` (club zone): dashboard "heute" and
  overdue follow-ups, weekly order value, "Kontakte heute". `due_on` stays a
  calendar date from the device; the server turns it into 09:00 club time as
  today.
- Authorisation, membership validity, delivery window availability, prices
  and suppression are evaluated at **send time**, never at `capturedAt`. A
  revoked acquirer cannot backdate a capture into their membership.

### 11.3 Price guard for queued orders

When `capturedAt` is present, `createCommitment` compares each line's
`quotedUnitPriceMinor` with the server price and refuses a difference with 409
`commitment_price_changed`, including the new unit prices and total in the
error details. Without `capturedAt`, internal capture keeps today's behaviour
(server price, quote ignored). Accepting the new price resends with the new
quote and a new key.

### 11.4 Activity recording with a moved assignment

Today a revision mismatch refuses the whole activity. Offline, a colleague's
entry on a shared sponsor is likely, and losing the acquirer's contact is
wrong: the contact happened.

Proposal (Q1): with `capturedAt` present and a revision mismatch, Core records
the activity (the fact) and the history entry, but **does not** change the
assignment's status, next action or due date. The answer is 201 with
`assignmentUpdated: false` and the current assignment. The PWA then shows the
follow-up conflict (§10.1) and can send "Meine Wiedervorlage übernehmen" as a
normal online update on the current revision. Without `capturedAt` the
behaviour stays as today (409).

### 11.5 Unchanged but relied on

- `command_receipt` keeps receipts for at least the queue retention (14 days);
  today it keeps them forever. A future retention job must keep ≥ 30 days.
- A refused command leaves no receipt (rollback), so a resolution with the same
  key (`allowFullWindow`, draft fallback with the same body is a new key anyway)
  works.
- The `Idempotency-Key` format stays; the PWA uses `pwa-q:<entryId>`.

### 11.6 API and client

All additions are optional request fields, one new optional response field
(`assignmentUpdated`), one new error code per case. No breaking change; the
OpenAPI breaking-change gate stays untouched. Regenerate the client.

## 12. UX and copy (Du)

### 12.1 Offline banner

Replaces the text in `mobile-shell.tsx:79` (in the PWA only; the admin web
shell does not queue):

- Offline, queue empty: "Du bist offline. Neue Kontakte, Wiedervorlagen und
  Bestellungen speichert LeonAid auf diesem Gerät und sendet sie, sobald du
  wieder online bist."
- Offline, queue not empty: same, plus "**3 warten auf Versand.**"
- Online, after a send: no banner; the indicator (12.2) shows the result.

`offline.html` (first visit without cached shell) becomes: "Gerade keine
Verbindung. Öffne LeonAid einmal mit Verbindung, damit es auch offline
startet."

### 12.2 Queue indicator

A counter on the network glyph in the PWA bar (`pwa-net`), with an accessible
name:

| State            | Badge           | Accessible name                          |
| ---------------- | --------------- | ---------------------------------------- |
| empty            | none            | "Online" / "Offline" (as today)          |
| waiting          | number, neutral | "3 Einträge warten auf Versand"          |
| sending          | spinner         | "Einträge werden gesendet"               |
| needs a decision | number, warn    | "1 Eintrag braucht deine Entscheidung"   |
| failed           | number, danger  | "1 Eintrag konnte nicht gesendet werden" |

Tapping it opens the "Warteschlange" sheet.

### 12.3 Per-entry status

Each entry in the sheet and next to the capture where it appears (sponsor
detail, contact log) shows one of: **Wartet auf Verbindung** · **Wird gesendet
…** · **Gesendet** · **Braucht deine Entscheidung** · **Konnte nicht gesendet
werden** · **Abgelaufen** · **Nicht mehr möglich**. Status is text plus icon,
never colour alone.

The capture confirmation changes when offline: contact → "Kontakt
gespeichert. Wird gesendet, sobald du wieder online bist."; order (prototype
copy) → "Bestellung gespeichert. Wird gesendet, sobald du wieder online bist.
Klara prüft die Bestellung und stellt danach die Rechnung aus."

### 12.4 Prices and windows offline

The order form shows a note under the total when the capture context is from
the read cache: "Preis vom 03.11., 18:40. Ändert er sich, fragt LeonAid dich
vor dem Senden." Windows show "(ausgebucht)" from the cache; choosing one asks
as online (the task 6.5 confirm), and the confirmation is stored in the entry
(`allowFullWindow`).

### 12.5 Sign-out and account switch

Sign-out with a non-empty queue: dialog "Noch 3 Einträge nicht gesendet. Wenn
du dich jetzt abmeldest, werden sie von diesem Gerät gelöscht." Choices
**Erst senden** (online only) · **Trotzdem abmelden** · **Abbrechen**.

### 12.6 iOS hint

On iOS (standalone display mode, `navigator.standalone`), the queue sheet
shows once: "Auf dem iPhone sendet LeonAid nur, solange die App geöffnet ist.
Öffne sie, wenn du wieder Empfang hast."

## 13. Platform limits

- **iOS:** no Background Sync, no Periodic Background Sync; a home-screen web
  app that is not open does nothing. Sending happens on open, focus and
  `online` while open (§9.1). WebKit's 7-day deletion of script-writable
  storage applies to Safari tabs; home-screen web apps have their own storage
  and are exempt according to WebKit, but storage can still be evicted under
  pressure. Both points are verified on a real device in stage 1, and the
  sheet says what the device allows (§8.5 `persist()`).
- **Android/Chrome:** the same page-based loop. Background Sync would work but
  is not used (one behaviour).
- **Clock:** device clocks can be wrong; bounded server-side (§11.2).
- **Multiple tabs / installed app + browser tab:** Web Locks and a
  `BroadcastChannel`; IndexedDB transactions keep entries consistent.
- **Storage quota:** a queue entry is < 5 KB; 1000 entries are far below any
  quota. The read cache for 200 sponsors is ~100 KB.

## 14. Privacy review

### 14.1 What is on the device

- Queue entries: sponsor id and display name (via the read cache), the
  acquirer's note (free text, may contain personal data), channel, outcome,
  follow-up, order lines, delivery address and contact for an order.
- Read cache: sponsor display names, city, status, follow-up text, and (Q2)
  phone and contact name.
- Not on the device: email addresses, invoice recipients, other people's
  orders, delivery board data, documents.

### 14.2 Measures

- Purpose: acquisition of the acquirer's own sponsors (existing purpose
  `PrivacyPurpose.ACQUISITION`); no new processing purpose.
- Minimisation (§8.2), encryption at rest (§8.4), retention 14 days / 7 days
  (§8.5), deletion on sign-out, account switch, membership end.
- Suppressed channels are in the read cache so that an email/phone contact to a
  suppressed sponsor is refused already offline.
- The privacy notice for members gets one paragraph: what the PWA keeps on the
  device, for how long, and how to delete it (sign out). Legal configuration
  texts are Björn's call (Q8).
- No analytics, no third-party scripts; CSP unchanged.

### 14.3 Driver view

The delivery board keeps its no-store rule: in the PWA its queries and
mutations have `gcTime: 0`, it hides itself offline and removes its cached
data and finished mutations (`delivery-board.tsx:224-249`). It is not part of
the read cache and not queued. The service worker change (§8.1) must not
cache any `/api/` response; a unit test pins this for `sw.js`.

### 14.4 Server

Receipts (`command_receipt`) hold a request hash and the result id, no
personal data. `captured_at` is not personal data beyond the existing
activity/order record.

## 15. Testing strategy

- **Unit (packages/features, vitest):** queue state machine, ordering per
  sponsor, dependency handling, backoff schedule, result classification
  (§9.4), conflict mapping (§10) — against a queue store interface with an
  in-memory implementation that is a real implementation, not a double (the
  `no_test_doubles` gate forbids `Fake*`/`Mock*` I/O ports and HTTP doubles).
- **Storage in a real browser:** IndexedDB, WebCrypto and Web Locks run in
  Playwright Chromium (and WebKit for the iOS engine) against the real stack;
  jsdom has neither non-extractable keys nor Web Locks. `fake-indexeddb` is
  not used.
- **Server (contract tests, real PostgreSQL):** activity idempotency (replay,
  changed content → `idempotency_conflict`, concurrent sends → one row),
  `capturedAt` bounds, `local_day` for a capture at 00:30 Berlin, the price
  guard, activity with moved assignment (§11.4), receipt rollback on refusal.
- **E2E (`tests/e2e`, real stack):**
  - offline capture → `context.setOffline(true)`; reload offline starts the
    app from the shell (§8.1); capture; online → sent once; server row
    checked.
  - conflict flows: a colleague's contact meanwhile, window switched to
    "ausgebucht" meanwhile (6.5 API), price changed meanwhile.
  - sign-out with pending entries; sign-in as another user deletes the queue.
  - **lost acknowledgement**: the send reaches Core, the answer is dropped,
    the resend replays. That needs `page.route` with `route.abort()` after
    `route.fetch()`, which the `no_test_doubles` gate allows only for specs
    listed in `tools/ci/reviewed_network_faults.json`. The new spec's entry
    (path, SHA-256, reason) is prepared in the implementation report and
    approved by Björn; agents do not edit the manifest.
  - `setOffline` itself is not gated.
  - WebKit project run for the iOS engine (Playwright WebKit is not iOS
    Safari; a manual check on a real iPhone is part of stage 1's done
    criteria).
- **Accessibility:** banner, indicator and sheet with the shared axe helper
  (`tests/e2e/axe.mjs`).

## 16. Stages and effort

| Stage                          | Content                                                                                                                                                   | Effort |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| 1 Offline start and read cache | SW serves the shell offline; identity summary; encrypted IndexedDB per user; sponsor list and capture context cache; clearing rules; iOS device check     | 3–4 d  |
| 2 Server                       | activity idempotency, `capturedAt` (activities, orders), price guard, activity with moved assignment, contract tests, client regeneration                 | 3 d    |
| 3 Queue and sync               | queue store, sync loop with Web Lock, backoff, result classification, contact attempts and orders queued, indicator, banner copy                          | 4–5 d  |
| 4 Conflicts and drafts         | resolution sheet (§10), sponsor drafts with dependencies, sign-out warning, docs (DOC-P012-style user help for the PWA), e2e incl. reviewed network fault | 2–3 d  |

Each stage ships behind a feature flag (`pwa_offline_queue`) so that the
truthful "nothing is saved offline" copy stays until stage 3 is live.

## 17. Open questions for Björn

1. **Q1 Contact kept when the assignment moved (§11.4).** Record the contact
   and report only the follow-up as a conflict, or refuse the whole entry as
   today? _Recommendation: keep the contact; it happened, and losing it is
   worse than a duplicate follow-up decision._
2. **Q2 Phone numbers offline.** Cache sponsor phone and contact name so that
   the acquirer can call from the list without data? _Recommendation: yes, phone
   and contact name only, no email; voice works where data does not._
3. **Q3 Stale read cache.** Block offline capture when the sponsor list is
   older than 7 days? _Recommendation: yes; older lists make conflicts the
   rule._
4. **Q4 Extra PIN for the queue.** _Recommendation: no; rely on device lock and
   the non-extractable key (§8.4)._
5. **Q5 Retention of unsent entries.** 14 days, then 2 days of warning?
   _Recommendation: yes; a Krapfentaxi campaign runs a few weeks, and the
   server bound for `capturedAt` uses the same 14 days._
6. **Q6 Shared phones.** Delete another user's queue on sign-in without asking
   (it is their data, the new user must not see it)? _Recommendation: yes, with
   the sign-out warning as the safeguard._
7. **Q7 Modules.** Keep tasks, materials, knowledge and inbox online-only in
   the first version? _Recommendation: yes; revisit after real use._
8. **Q8 Privacy notice.** Add the device-storage paragraph to the members'
   privacy notice in the legal configuration (four-eyes flow)? _Recommendation:
   yes, before stage 3 goes live._
9. **Q9 Offline orders as drafts.** Send offline orders as captured (review-ready
   when complete), or always as drafts that the acquirer confirms online?
   _Recommendation: as captured; conflicts are handled per entry, and drafts
   would double the acquirer's work._
10. **Q10 Sponsor drafts.** Allow drafting a new sponsor offline at all (§10.4)?
    _Recommendation: yes, draft only, resolved online with the existing match
    step; fairs are the main offline case._

## 18. Risks

- **R1 Silent duplicates through a second device.** Two devices of the same
  acquirer capture the same contact offline. Idempotency keys are per entry,
  so both are recorded. Mitigation: none automatic; the contact log shows both,
  and the acquirer can delete one (existing function). Accepted.
- **R2 iOS storage eviction.** Possible loss of unsent entries on iOS under
  storage pressure. Mitigation: `persist()`, visible count, prompt to open the
  app; verified on a device in stage 1.
- **R3 Old cached PWA after a server change.** A cached PWA without the new
  fields keeps working because the fields are optional for one release (§11.1).
- **R4 Clock manipulation.** Bounded to −14 days / +5 minutes; authorisation
  at send time (§11.2).
- **R5 More data on devices.** Minimisation and retention as above; reviewed in
  Q2, Q8.
