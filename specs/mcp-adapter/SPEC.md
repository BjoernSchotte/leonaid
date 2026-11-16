# MCP adapter: operating LeonAid from an AI client

Status: 2026-11-16. Specification for review. Nothing in this document is
implemented. Implementation needs a separate go per stage (§11).

## 1. Why

Björn wants to run the club's installation from an AI client (Claude Code,
Claude Desktop, claude.ai) instead of clicking through the admin UI. On
2026-11-16 that meant driving the REST API from a browser session and
forwarding login codes from his mailbox to get anything done. That works, but
it is fragile and puts one-time codes into a chat.

The architecture already reserves this path (ADR-0003, `specs/produkt-und-
architekturvorschlag.md` "Spätere FastMCP- und LLM-Erweiterung"): an MCP
adapter in front of the same application services as FastAPI, with no second
business logic. This spec makes it concrete and changes one rule from that
section (§3.3).

## 2. Goals, non-goals, anti-goals

Goals:

- A person with a LeonAid account connects an MCP client once and then reads
  and changes what their roles allow, without the browser and without mail
  codes per session.
- The important workflows of a running action are covered (§6): status,
  orders, delivery, invoices and payments, donations, action settings,
  aliases and domains, legal configuration, members and roles.
- Every call is authorised, audited and idempotent exactly like the same
  action in the web UI.

Non-goals:

- No LLM inside LeonAid. The model runs in the client; LeonAid only exposes
  tools.
- No MCP tools generated automatically from all FastAPI endpoints.
- No anonymous or public tools (public order form, surveys, campaign pages).
- No direct database, Twenty, RustFS or file-system access through MCP.
- No CMS editing (EmDash has its own editor).

Anti-goals, which would make this a failure even if it works:

- A tool that can do more than the same person can do in the web UI.
- A second implementation of a rule (status transitions, invoice numbering,
  revision checks) inside the adapter.
- Personal data of buyers or members in server logs because of MCP.
- A token that cannot be revoked at once, or that outlives the account's roles.

## 3. Authentication and authorisation

### 3.1 Access tokens

A new credential type next to the session cookie: the **access token**.

- A signed-in user creates it under **Konto › Zugänge für Programme**, after a
  fresh login. Fields: a name such as "Claude auf dem Laptop", an expiry
  (default 90 days, at most 365), and the access level, either **Lesen** or
  **Lesen und ändern**.
- LeonAid shows the token once (`la_pat_` + 43 random URL-safe characters) and
  stores only its SHA-256 digest, the same pattern as session tokens.
- The list shows name, level, created, expires and last used (date only), and
  offers **Widerrufen**. A system admin sees and revokes the tokens of all
  accounts under System › Konten.
- A token dies with its account: suspending or archiving the account, or the
  expiry, ends it at once. Revocation takes effect on the next call, because
  the server checks the digest per request and does not cache it.
- At most 10 active tokens per account.

### 3.2 Roles

A token carries **no roles of its own**. Each call resolves the account's
current global roles (`system_admin`, `finance_reader`, `finance_manager`) and
action roles (`charity_admin`, `acquirer`, `finance_reader`, `driver`) exactly
as the session path does (`IdentityPrincipal`). Whatever the user may do in the
web UI, the token may do. Whatever the user loses, the token loses on the next
call. The access level **Lesen** additionally refuses every write tool.

### 3.3 Approvals: roles decide, not four eyes

Decided by Björn on 2026-11-16. Changing finance-relevant data (invoices,
payments, cancellations, donations, donation receipts) through MCP needs **no
four-eyes step and no extra human confirmation**. The roles of the token's
user decide, as in the web UI. This replaces the sentence "Schreibende oder
finanzrelevante AI-Aktionen benötigen eine explizite, serverseitig geprüfte
menschliche Freigabe" in the architecture proposal.

Domain rules that exist independently of MCP stay as they are. The legal
configuration still needs a second system admin to approve a draft
(`legal_configuration_four_eyes_required`). Through MCP this means the drafter
and the approver are two accounts with two tokens. Whether that rule should
change is a separate product decision, not part of this spec.

### 3.4 Fresh login

Commands that need a fresh login in the web UI (legal configuration, renderer
switch, cancelling paid orders and so on) accept an access token of level
**Lesen und ändern** as fresh. Creating the token already required a fresh
login, and the token is a deliberate, revocable credential. A token of level
**Lesen** never counts as fresh.

## 4. Transport and placement

- **Server:** FastMCP, pinned to an exact version in `pyproject.toml` and
  `uv.lock`, mounted as an ASGI sub-application at `/mcp` in the existing Core
  container. No new container, no new port.
- **Transport:** Streamable HTTP on the admin host
  (`https://app.<club>.leonaid.org/mcp`) only. The public host and the
  campaign domains return 404.
- **Authentication:** `Authorization: Bearer la_pat_…`. A session cookie is not
  accepted at `/mcp`, and an access token is not accepted on the REST API. Each
  path keeps a single credential type and its own CSRF reasoning.
- **Client configuration:** the token page shows a ready-to-copy snippet for
  Claude Code (`claude mcp add --transport http leonaid <url> --header
  "Authorization: Bearer …"`) and for Claude Desktop.
- **Feature flag:** `mcp.enabled`, off by default and switched on per
  installation under System › Funktionen. While it is off, `/mcp` returns 404
  and the token page is hidden.

## 5. Tool design rules

1. **One tool, one use case.** A tool calls exactly one application service
   method, the one the REST route calls. It contains no business rule.
   Mapping between MCP arguments and service arguments is the only code.
2. **Named by the task, in English, in snake_case:** `list_orders`,
   `record_invoice_payment`. Descriptions are short English for
   the model. Tool results keep German product terms and status labels as the
   UI shows them.
3. **Write tools are idempotent.** They take a `command_id` (UUID) that the
   client generates per intent, and pass it on as the REST API passes its
   command IDs. A repeated call returns the stored result.
4. **Revision-checked writes** take `expected_revision`, as the REST bodies do.
   A conflict returns the current state so the model can re-plan without a
   second read.
5. **Errors** are MCP tool errors carrying LeonAid's `code` and German
   `message` (for example `order_form_missing`). Nothing is translated or
   rephrased.
6. **Small results.** List tools paginate (default 25, at most 100) and return
   only the fields needed to decide the next step. Detail tools return the full
   record. No binary documents: invoices and receipts come back as metadata
   plus an admin URL, never as PDF bytes.
7. **Annotations:** read tools set `readOnlyHint`; destructive tools
   (cancel, storno, revoke) set `destructiveHint`, so clients can ask before
   calling them.

## 6. Tool set (stage 1 and 2)

Read tools (level **Lesen**):

| Tool                           | Service                                   |
| ------------------------------ | ----------------------------------------- |
| `whoami`                       | identity: account, roles, token level     |
| `list_actions` / `get_action`  | actions: summary, status, configuration   |
| `get_action_dashboard`         | dashboard figures                         |
| `list_orders` / `get_order`    | commitments, with status and delivery     |
| `list_invoices` / `get_invoice`| invoices, payments, open amounts          |
| `list_donations`               | donations and receipts                    |
| `list_delivery_tours`          | delivery tours and stops                  |
| `list_tasks`                   | tasks of an action                        |
| `search`                       | core search (sponsors, orders, contacts)  |
| `get_legal_configuration`      | active version, draft, findings           |
| `list_site_hosts`              | domains, bindings, TLS state              |
| `get_operations_status`        | doctor-style health, backups, versions    |

Write tools (level **Lesen und ändern**):

| Tool                                                        | Service                                   |
| ----------------------------------------------------------- | ----------------------------------------- |
| `record_order`                                              | internal order capture                    |
| `cancel_order`                                              | order cancellation (with storno rules)    |
| `issue_invoice` / `send_invoice`                            | invoices                                  |
| `record_invoice_payment`                                    | payments                                  |
| `cancel_invoice`                                            | Stornorechnung                            |
| `record_donation` / `issue_donation_receipt`                | donations                                 |
| `set_order_form_open`                                       | order form status (E-064)                 |
| `set_action_status`                                         | lifecycle transitions                     |
| `set_campaign_renderer`                                     | alias renderer (E-063)                    |
| `save_legal_draft` / `approve_legal_draft` / `activate_legal_version` | legal configuration (§3.3)      |
| `invite_member` / `set_member_roles`                        | identity                                  |
| `create_task` / `complete_task`                             | tasks                                     |
| `resend_buyer_mail`                                         | buyer mails                               |

Stage 3 (separate go): surveys, materials, knowledge pages, inbox cases,
delivery planning edits, site-host binding.

## 7. Audit and privacy

- Every write through MCP writes the same audit event as the web UI, plus
  `channel: "mcp"` and the token ID (never the token) in the payload. The audit
  view filters by channel.
- The server logs tool name, token ID, account ID, duration and result code.
  It never logs arguments or results, because they contain buyer and member
  data.
- Tool results contain personal data only where the same user sees it in the
  UI. The privacy notice for members (Rechtliches › Datenschutzhinweis für
  Mitglieder) gets a sentence on access tokens: what they are, and that
  processing happens in the AI client the member chooses. The member, not
  LeonAid, is responsible for that client.
- Rate limit per token: 120 calls per minute and 20 writes per minute, then
  429 with `retry_after`.

## 8. Data model

New table `access_token`:

| Column                      | Notes                                   |
| --------------------------- | --------------------------------------- |
| `id`                        | uuid                                    |
| `user_id`                   | FK `user_account`                       |
| `name`                      | 1–80 chars                              |
| `token_digest`              | sha256 hex, unique                      |
| `access_level`              | `read` or `read_write`                  |
| `created_at`, `expires_at`  |                                         |
| `last_used_on`              | date, updated at most once per day      |
| `revoked_at`, `revoked_by`  |                                         |

Migration: additive only (release-updates rule zero). Creating and revoking a
token writes the audit events `access_token.created` and
`access_token.revoked`.

## 9. Testing

- One contract test per tool through the MCP transport against real
  PostgreSQL. It checks the call with a permitted role, a refused role, a token
  of level **Lesen** (refused for write tools), idempotent repetition (writes),
  and the revision conflict where it applies.
- A guard test fails when a write tool does not take `command_id`, or when a
  tool module imports from `leonaid.adapters` (the adapter must only call
  application services).
- A role-matrix test asserts that for every tool, the MCP result for each role
  equals the result of the matching REST route for that role.
- No E2E browser tests; MCP has no UI beyond the token page, which gets the
  usual component tests.

## 10. Documentation

- How-to (de and en): "LeonAid mit einem KI-Client bedienen". It covers
  creating a token, connecting Claude Code and Claude Desktop, revoking a
  token, and what the access level means.
- Reference: the tool list, generated from the tool registry as the OpenAPI
  reference is.
- An ADR amendment to ADR-0003 for §3.3 and §3.4.

## 11. Stages

1. **Tokens and read tools.** Table, token page, `/mcp` with the read tools in
   §6, feature flag, docs. Useful on its own: status questions without the
   browser.
2. **Write tools.** The write list in §6, audit channel, rate limits.
3. **Remaining areas** from §6 stage 3.

Each stage is one PR with its own release.

## 12. Decisions taken in this spec

Björn's:

- Finance-relevant writes need no four-eyes step or extra confirmation. The
  token user's roles decide (§3.3).

Mine, open for review:

- Tokens carry no roles of their own; they act with the account's current
  roles, with a read-only level as the only narrowing (§3.2).
- A token of level read and write counts as a fresh login (§3.4).
- The legal four-eyes rule stays a domain rule, outside this spec (§3.3).
- Separate credentials: no cookies at `/mcp`, no tokens on the REST API (§4).
- FastMCP inside the Core container behind a feature flag, with no new
  service (§4).
- Expiry of 90 days by default and 365 at most; 10 tokens per account; rate
  limits as in §7.
