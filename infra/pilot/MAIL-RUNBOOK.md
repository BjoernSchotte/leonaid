# Production mail transport

LeonAid sends transactional messages over SMTP, independent of the provider.
Provider choice, domain approval and real credentials remain private pilot
decisions; Mailpit is development and test infrastructure only.

## Configuration boundary

The API gets only `MAIL_HEALTH_URL`. SMTP host, visible sender,
envelope-from, reply-to, transport mode and credentials are injected into the
worker; in the pilot, `twenty-server` and `twenty-worker` get the same relay
and credentials for Twenty's own mail (address verification, password
reset), with the sender `TWENTY_MAIL_FROM_ADDRESS` from the domain of
`MAIL_FROM`. Only `worker` and `twenty-worker` are attached to the
non-internal network `mail-egress`, the only path to the relay. A filled-in
copy of `mail.env.example`, provider contracts, credentials and test mailbox
contents must never reach Git or public CI artifacts.

Supported modes:

- `starttls`: the connection must be upgraded to TLS after `EHLO`;
- `tls`: TLS is in place from connection setup;
- `plain`: only for local/isolated tests, refused in production.

Twenty 2.54 (nodemailer) uses implicit TLS on port 465 and otherwise
upgrades with STARTTLS only if the relay offers it; Twenty has no option to
require STARTTLS, so an attacker on the path could strip it. Twenty therefore
sends mail only with `MAIL_SMTP_MODE=tls`: the entrypoint policy in
`infra/pilot/compose.yml` selects `EMAIL_DRIVER=SMTP` for `tls` and
`EMAIL_DRIVER=logger` (no mail) for every other mode, and `pilot-doctor`
prints a warning for `starttls`. The core worker enforces STARTTLS itself and
keeps sending in both modes. The deployment contract requires `tls` exactly
with port 465 and `starttls` with another port.

In production, certificate verification is mandatory. Locally and in isolated
tests, a private CA can be referenced through `MAIL_SMTP_CA_FILE`; in the
pilot this is refused, because Twenty trusts only public CAs.
Username and password must be set together or be empty together.
In production, all three sending identities are also explicit:

- `MAIL_FROM`: visible sender in the message;
- `MAIL_ENVELOPE_FROM`: technical return address for bounces;
- `MAIL_REPLY_TO`: staffed reply path for questions.

The transport rejects messages with a different visible sender or reply-to
as terminal and passes the envelope-from to SMTP separately.
Login, fresh login, invitation and invoice messages state in the text that
questions sent as a reply to the message reach the staffed reply-to path.

## Domain approval

The confirmed private expectation is derived outside the repository from
`mail-domain.expected.example.json`. Before staging, after every DNS/provider
change and before production approval:

```sh
./leonaid mail-domain-check \
  --expectation /etc/leonaid/mail-domain.expected.json \
  --report /var/lib/leonaid/evidence/mail-domain-readiness.json
```

The check queries a real public resolver and blocks on:

- envelope-from, from or reply-to not aligned with the confirmed domain;
- missing, duplicate or incomplete SPF;
- missing, revoked or unexpected DKIM key;
- missing DMARC, wrong policy or less than 100 percent coverage.

The report contains no mail addresses and no DNS TXT contents, only
domain, selector, boolean results, counters and SHA-256 fingerprints.
`./leonaid test-mail-domain` proves the contract in CI against a public DNS
fixture not controlled by LeonAid, with four fail-closed mutations. The CI
proof does not replace the private run against the actual pilot domain.

## Approval

Before production sending, the following must be done and privately
evidenced:

1. relay, domain owner and controlled test mailbox selected;
2. SPF, DKIM and DMARC checked on the production DNS;
3. STARTTLS or implicit TLS with certificate verification successful;
4. login, invitation, email correction and invoice delivered in the provider
   sandbox or test mode;
5. provider limits, bounce/abuse path, alerting and incident owner
   defined;
6. no address, token, provider text or mail content in logs or public
   evidence files;
7. visible from, reply-to, envelope-from and Message-ID checked on the
   receiving system;
8. at least one controlled mailbox at each of two different mail providers
   receives magic link/code, invitation and invoice; result, time and
   provider are recorded only privately.

`./leonaid test-mail-relay` proves locally, with pinned real services,
STARTTLS, authentication, certificate errors, timeout, provider limit and a
retry accepted exactly once. This contract does not replace the separate
real provider proof.

## Responsibility and delivery failures

Before approval, a primary mail operator and a deputy are confirmed by name
in the private decision record. The repository deliberately contains no
private names. This role:

1. watches provider status, LeonAid operations and the dead letter queue;
2. correlates a failure only by time window, safe error code, event type
   and internal ID;
3. checks before a retry whether the provider has already accepted the
   message;
4. retries only the selected failed event;
5. informs affected people if needed through a previously authorized
   alternative channel, without copying a magic link, code, invoice or mail
   content into tickets;
6. documents decision and result in the private pilot evidence store.

Temporary `4xx` responses, limits, timeouts and connection errors may be
retried automatically up to the configured outbox maximum. After that they
stay visible in the dead letter queue. Permanent recipient rejection,
authentication and certificate errors are terminal and are not retried
automatically without end.

Until a later webhook integration, the named role handles provider bounces
and complaints in the protected provider portal. A hard bounce or a complaint
never leads to a manual blind retry. First, the cause and the consent or a
functionally valid contact path are clarified. Provider-specific bounce
classes, complaint channel, retention and response time are added in the
private provider decision; without this evidence, the production mail
approval stays open.

## Operation and outages

Core readiness does not depend on the relay: acquisition, campaigns and
document access stay available during a mail outage. The operations view
reports the mail path separately as degraded; outbox events are kept
durably and can be processed again safely after the fix.

Error codes are deliberately free of provider details and personal data:

- `mail_authentication_failed`
- `mail_certificate_invalid`
- `mail_timeout`
- `mail_provider_limited`
- `mail_temporary_rejection`
- `mail_permanent_rejection`
- `mail_recipient_rejected`
- `mail_transport_unsupported`
- `mail_tls_failed`
- `mail_protocol_failed`
- `mail_unavailable`

On authentication or certificate errors, check secret/certificate rotation
and provider status first. On temporary limits or timeouts, the outbox retry
stays active. A deliberate functional resend of an invoice that was already
delivered is separate from a technical retry.

## Rotation

### SMTP credentials

1. create a new secret at the provider; do not revoke the old one yet;
2. update the worker-only secret store;
3. restart the worker in a controlled way and check readiness;
4. deliver a synthetic login and one controlled invoice;
5. only then revoke the old secret and store the evidence privately.

### DKIM

1. publish the new selector in parallel;
2. run `mail-domain-check` green with the new selector;
3. switch provider signing to the new selector;
4. check delivery and DKIM result at both test providers;
5. remove the old selector only after the agreed overlap window.

Changes to from, envelope-from, reply-to, SPF or DMARC are first prepared with
the domain owner and provider, then checked publicly, and only then taken
over into the worker. A DNS or identity change without a green check is a
STOP.

## Provider outage and recovery

During an outage, core, documents and acquisition stay available. The
operator:

1. confirms the impact through provider status, operations and safe error
   codes;
2. stops repeated manual retries and records the start privately;
3. keeps automatic, bounded outbox retries in place if the failure is
   temporary;
4. informs the pilot leads and affected users through the agreed
   alternative channel;
5. switches the provider only after a new domain, TLS, identity and delivery
   approval.

After the provider recovers, check health, certificate and
`mail-domain-check`. Then send one controlled login/invitation message and one
invoice. Only when Message-ID, identities, PDF hash and exactly one acceptance
match are selected dead letters retried safely. Completion time, count,
error classes and result go only to the private evidence store; after that
the mail status is set back to normal.
