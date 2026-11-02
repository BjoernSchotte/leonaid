# LeonAid personas

This document is the central, short product reference for everyone who uses
or operates LeonAid, or who is affected by a charity action. It turns the
detailed product concept into concrete goals, usage contexts and access
boundaries.

The authoritative sources for details remain
[`specs/produkt-und-architekturvorschlag.md`](specs/produkt-und-architekturvorschlag.md)
and the proven PoC state in
[`specs/leonaid-poc/PLAN.md`](specs/leonaid-poc/PLAN.md).

## Maintenance contract

Update `PERSONAS.md` in the same task when a persona, role, permission,
navigation, core task or PoC boundary changes. A task is not complete in
substance if its product or permission decision contradicts this document.

Four guardrails apply:

1. A persona and a technical role are not the same thing. One person can hold
   several roles.
2. Action roles apply only to the specific charity action.
3. Hidden UI elements never replace server-side authorization.
4. Action-specific roles appear only when the matching capability is active.

## PoC personas

### Charity admin

**Goal:** Prepare a charity action, run it day to day and close it in a
traceable way.

**Context:** Volunteer Lions member, mostly on a desktop and often in short
work sessions. The charity admin manages only their own actions.

**Core tasks in the PoC:**

- maintain the action, period, goal, beneficiaries and public presentation;
- invite members to actions they manage;
- assign and revoke action roles only in actions they manage;
- keep an overview of companies, contacts, acquirers and multiple assignments;
- review internal and public orders;
- approve invoices after a fresh sign-in;
- download and send the invoice PDF, and retry sending in a controlled way;
- record an exact full payment manually;
- cancel an invoice with a reason, without overwriting the record or PDF;
- understand the action-wide sponsor pipeline, orders, order value, invoiced
  amount and open items on the dashboard;
- move from any dashboard metric to the work list, already filtered by action
  and status.

**Access boundary:** `charity_admin` is an action role. It grants no rights on
other actions and no global system or finance roles. The last charity admin of
an action that can still change operationally cannot be removed without a
replacement.

**Interface:** Responsive back-office web app; some CRM tasks can also happen
in Twenty.

### Acquirer

**Goal:** Win companies or personal contacts as sponsors and reliably record
the next step.

**Context:** Lions member, often on the move, with varying technical
confidence.

**Core tasks in the PoC:**

- see their own and jointly assigned companies or people;
- create a new sponsor and see existing acquirers when a match is found;
- add themselves as an additional acquirer after explicit confirmation;
- record contact attempts, outcomes and follow-ups;
- record an order or commitment;
- see public orders from their own contacts under „Neues“ (new);
- see their own pipeline, follow-ups, activities and the next sensible step on
  the personal dashboard;
- follow action progress with value, unit and plain text as motivation, and
  move directly to a filtered sponsor list.

**Access boundary:** `acquirer` applies per action and only to assigned CRM
parties. An assignment grants no access to invoices, finance documents or
charity administration. Acquirers get no Twenty account of their own in the
PoC.

**Interface:** Installable, mobile-first PWA; it shares components and
features with the responsive web app.

### Public customer or sponsor

**Goal:** Understand a charity action and submit a binding order or commitment
without an account.

**Context:** Opens a promoted link or QR code on a smartphone or desktop and
does not know LeonAid beforehand.

**Core tasks in the PoC:**

- understand the purpose, period and beneficiaries;
- choose offer, price and quantity;
- enter company or personal contact details and delivery/billing details;
- submit the form with protection against double submission;
- receive a clear confirmation.

**Access boundary:** No LeonAid account and no access to internal data. Only
published action pages and explicit forms are reachable.

**Interface:** Lean, accessible Astro action page.

### Finance officer or treasurer

**Goal:** Reliably check outgoing invoices, sending, payments and open items.

**Context:** Works mostly on a desktop and needs immutable records and
traceable exports for further accounting processes.

**Core tasks in the PoC:**

- check invoice data and Typst PDFs;
- trace approval and sending status;
- tell open and paid invoices apart;
- check incoming payments, cancellations and correction history.

**Current permission split:**

- `finance_reader` (global or per action) reads invoices, finance documents
  and status, but cannot record anything;
- `finance_manager` is a global role, granted only by the system admin, for
  full payment and cancellation;
- a charity admin holds the same finance actions only in actions they manage.

The golden-data user **Finn Finanzen** is `finance_reader` on purpose and
proves the read-only case. The PoC has no permanently maintained golden login
for `finance_manager` yet; the role exists technically.

**Interface:** ERP-light area of the back-office web app.

### System admin

**Goal:** Run a single club installation securely, available and recoverable.

**Context:** Technically experienced Lions member or a contracted operator.
Tenants are separated by separate installations.

**Core tasks in the PoC:**

- operate the Docker Compose deployment, secrets and integrations;
- manage users, global roles, action roles and sessions;
- trace open, accepted, expired and revoked invitations within the permitted
  action scope, revoke them or resend them in a controlled way;
- correct a wrong login email after a fresh sign-in as a pending change,
  without deactivating the previous address before confirmation;
- configure Twenty, PostgreSQL, RustFS and the mail relay;
- turn catalogued feature flags on and off for controlled rollouts and check
  their revision and effect;
- check privacy evidence and contact blocks for an exact email address,
  generate a portable data access report and run a controlled anonymization
  workflow;
- keep immutable invoice records on purpose while doing so, and keep the
  legal, retention-period and Twenty deletion decisions that are still open in
  the PoC visible;
- run updates, health checks, diagnostics, backup and restore.

**Access boundary:** `system_admin` is system-wide and therefore must not be
used as an everyday business role. Critical actions require a fresh sign-in
and an audit entry. Feature flags change visibility or rollout, never role or
record permissions. The last active system admin cannot be removed. Members
cannot change their own login email in the pilot. A change started by the
system admin becomes active only after confirmation by link or code at the new
address, and it revokes only the sessions of the affected account.

**Interface:** System area of the web app, including the protected privacy
workspace and the UI review catalog, plus versioned Docker/runbook tools.

## Downstream or external personas

### Driver

**Goal:** Deliver the assigned orders of an action with little coordination
effort.

**Context:** Mobile, action-specific persona of the Krapfentaxi.

**Later tasks:** See the tour and stops, use only the necessary delivery data,
open navigation and record delivery status.

**Status:** Deferred until after PoC/MVP. `driver` is only an action role with
an active `delivery` capability and does not appear automatically, for example
for Lions Open.

### Beneficiary contact

**Goal:** Present the beneficiary organization correctly and receive
information on the action result.

**Context:** External contact person without a LeonAid account.

**Tasks:** Supply master data, a description of the purpose and, if needed,
images; receive the result.

**Status:** Stakeholder, not a technical PoC role.

## Roles and scope

| Technical role    | Scope                  | Product meaning                        |
| ----------------- | ---------------------- | -------------------------------------- |
| `system_admin`    | global                 | operations, users and integrations     |
| `finance_reader`  | global or action       | read invoices and finance status       |
| `finance_manager` | global                 | record finance status, control cancels |
| `charity_admin`   | action                 | fully manage their own charity action  |
| `acquirer`        | action                 | acquire assigned sponsors              |
| `driver`          | action with `delivery` | later delivery                         |

Further action-specific roles such as `player`, `tournament_admin`,
`booth_operator` or `volunteer` will be defined only with the matching
capabilities and the downstream use cases Lions Open and Christmas market.

### Role management

- Only a system admin may grant or revoke global roles.
- A system admin may manage all action roles available for an action.
- A charity admin may manage action roles only in actions they manage; global
  roles and other actions stay blocked both in the interface and through
  direct API calls.
- `driver` is offered only when the specific action has the `delivery`
  capability. The productive delivery workflow stays deferred in the pilot.
- Every change requires a freshly confirmed sign-in, an idempotency key and
  the expected revision. Conflicts are shown clearly and successful changes are
  audited.
- Roles take effect on navigation, lists, exports and document access from the
  next request, without a new sign-in.
- A revocation ends the permission but deletes neither the historical
  membership nor existing business assignments, activities, invoices or
  document references.

## Shared UX requirements

- business terms instead of internal IDs, Twenty object names or technical
  jargon;
- status, consequence and next step are clear without relying on color;
- mobile core actions stay at least 44 pixels in size and reachable;
- important admin and finance actions require a fresh sign-in;
- light, dark and system mode are equal;
- errors explain the problem, its effect and a possible correction;
- historical finance and activity data stay traceable after role changes,
  blocking or archiving.

## Proven device and acceptance matrix

The shared responsive code is not derived only from the primary usage
contexts. POC-102 proves the critical paths on both device sizes on purpose:

| Persona         | Primary proof                               | Responsive cross-check                 |
| --------------- | ------------------------------------------- | -------------------------------------- |
| Charity admin   | Desktop dashboard and open invoice          | Invoice list on a smartphone           |
| Acquirer        | Smartphone pipeline and order entry         | Order entry on a desktop               |
| Public customer | Smartphone action page and error correction | Desktop stays responsive through Astro |

For these paths, keyboard focus, screen reader texts, 200 percent text
zoom, mobile core actions of at least 44 pixels, WCAG automation and
reproducible performance budgets are part of the Definition of Done. The
detailed proof is in
[`specs/leonaid-poc/proofs/POC-102.md`](specs/leonaid-poc/proofs/POC-102.md).
