# Pilot onboarding and support

This runbook describes the reproducible process for `PILOT-051`. It is for
club leads and operators; database access, internal IDs and insight into
functional form data are not required.
A technical test run replaces neither a confirmed pilot group nor moderated
sessions with real people.

The portal UI is German. UI labels below are quoted as shown in the portal,
with an English gloss.

## Roles and limits

- **System admin** invites members, manages installation-wide roles,
  locks accounts, revokes sessions and handles technical support codes.
- **Charity admin** invites members only into charity campaigns they manage
  themselves and manages their campaign-scoped roles.
- **Acquirer** maintains sponsors and commitments for assigned campaigns.
- **Finance** checks, creates, sends and books invoices.
- **Pilot coordination** confirms the pilot group, period, privacy notice,
  support window and abort criteria outside LeonAid.

Every real person gets an individual account. Shared accounts, forwarded
login codes and members changing their own email address are excluded in the
pilot.

## 1. Confirm the pilot before the first login

Pilot coordination records in the private evidence store:

1. approved real people and the roles they need;
2. managed charity campaigns per charity admin;
3. start, end, support hours and a reachable escalation channel;
4. the privacy notice sent and the lawful use of data;
5. release ID and commit of the approved version;
6. abort criteria for a suspected privacy, authorization or data loss issue.

Only a non-guessable evidence ID and totals without personal data belong in
the repository. Names, email addresses, login codes and support contents stay
in the protected evidence store.

## 2. Invite a member and check first access

1. As system admin, open `Mitglieder` (Members) and select
   `Mitglied einladen` (Invite member).
2. Check the email address once against the confirmed pilot list.
3. Assign only the installation-wide role that is needed.
4. For a campaign role, select the specific charity campaign.
5. Send the invitation. The assignment applies immediately after the
   confirmed invitation.
6. The invited person requests a code on `Login` themselves and signs in
   with it.
7. Check together that navigation and work context show only the intended
   areas.

A charity admin repeats the same flow for a campaign they manage. The
negative proof must show that other campaigns cannot be selected or written
to.

## 3. Change a role, lock an account and revoke sessions

These actions run only in `Mitglieder` (Members):

1. open the affected member;
2. change the role or campaign-scoped assignment and save;
3. on revocation, immediately run `Sitzungen entziehen` (Revoke sessions);
4. for offboarding, also lock the account;
5. check with a fresh sign-in that revoked areas are no longer reachable.

Important administrative actions require a fresh sign-in. In the pilot, the
system admin performs an email correction; the member cannot change the
address themselves. Direct database changes count as a failed operator
proof.

## 4. Pass a support code to the support team

Every normal API error message states the impact, the next step and a
support code. The affected person sends only:

- the full support code;
- the rough work area;
- the observed time;
- whether a retry has already happened.

Do not send: form contents, names, email addresses, postal addresses,
login codes, cookies, tokens, screenshots with real data or documents.

## 5. Diagnose a request safely as system admin

1. Open `System` (tab `Betrieb`, operations).
2. Under `Support-Code nachschlagen` (look up a support code), paste the
   full support code.
3. Select `Sicher nachschlagen` (Look up safely).
4. Check the result, impact, route, status, error code, release and next
   step.
5. Work through the operations status and the runbook that matches the error
   code.
6. Only then guide exactly one new functional attempt.

Per API process, the diagnosis stores at most the last 2,000 requests, and
only:

- support code and time;
- HTTP method and normalized route template;
- HTTP status and stable error code;
- release.

Query parameters, request/response payloads, headers, identities and
functional data are not stored. After a process restart the ring buffer is
empty. If a code is not found, the action is reproduced at most once in a
controlled way; payloads or database contents are never read for this.

The `Diagnose-Test starten` (Start diagnostic test) button deliberately
creates a write-free `support_probe_failed` error. It is for training only
and must not be counted as a real incident.

## 6. Collect feedback with minimal data

The template [`FEEDBACK-TEMPLATE.md`](FEEDBACK-TEMPLATE.md) is copied into the
private evidence store once per observation. The coordinator removes
unnecessary personal data, prioritizes the finding and assigns it to a
release ID. Public evidence contains only aggregated counts, priority, status
and a non-guessable evidence ID.

Before pilot activation, P0/P1 usability and accessibility findings must be
closed and proven again. P2 needs an owner, a target release and an explicit
pilot decision.

## 7. Escalation and closure

- **P0:** stop the pilot immediately, lock write access, apply the incident
  and recovery runbook.
- **P1:** disable the affected flow or limit access; prove the fix and
  regression before resuming.
- **P2/P3:** document owner, release and decision.

On offboarding, roles are removed, sessions revoked and the account locked.
The person then confirms that a fresh sign-in no longer grants access. The
coordinator records only the private evidence ID and a result without
personal data.

## Reproducible partial technical proof

```sh
./leonaid test-unit
./leonaid test-operations
```

`test-operations` uses an empty, isolated stack with real PostgreSQL, Twenty,
RustFS, Mailpit, worker and browser. It creates the controlled error,
correlates its support code, checks that no payloads are stored and that
system admin protection holds, and then removes containers, networks and
volumes.
