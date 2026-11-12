---
title: Deploy a pilot installation
description: Deploy a manifest-bound staging or production installation without building on the target host.
docId: DOC-P022
audience: [ops]
diataxis: how-to
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 86b4e396de4569cbc7dbd03cdb2153a8698bb0d1
reviewer: Björn Schotte
---

Define separate domains, Compose projects, volumes, buckets, SMTP credentials,
Restic repositories, and secrets for staging and production. A further
organisation gets a further installation.

1. Copy `infra/pilot/production.env.example` outside the repository. The
   completed file belongs to the operator account and has mode `0600`.
2. Copy the lines of `release-images.env` from the approved GitHub release
   (see [Release a version](/en/ops/how-to/release-a-version/)): version,
   full `LEONAID_RELEASE_COMMIT` and images with tag and digest. Add an
   external backup target.
3. Render and inspect the effective configuration with `docker compose ...
config --format json`, using `infra/compose/compose.yml` and
   `infra/pilot/compose.yml`.
4. Run `./leonaid pilot-doctor --env-file ENV --backup-manifest MANIFEST
--gate pilot-deploy`. Exit 0 means technically ready, 1 means a blocker, 2
   means open decisions, and 3 means a STOP decision.
5. Deploy only an approved release manifest with `./leonaid pilot-deploy
--env-file ENV --backup-manifest BACKUP --release-manifest RELEASE`.

The target host does not build and exposes only Caddy on ports 80/443.
Staging is optional and may run on another host, for example a VM in the
club's own network. A staging installation waits for no decision in the
register. A real production start stays blocked while DNS, trusted TLS, mail,
operator details, recovery target, or business decisions remain open.

## Staging behind a proxy and without an SMTP account

Two options make a staging VM in the club's own network easier. The doctor
refuses both when `LEONAID_DEPLOYMENT_STAGE=production`.

- **`LEONAID_EDGE_TLS=true`:** a reverse proxy or tunnel in front of the
  server (for example Pangolin or Cloudflare Tunnel) owns the public
  certificate and port 80. Caddy then uses its internal CA. The proxy
  forwards HTTPS to port 443 of the server, with the public host name as
  TLS server name (SNI). The doctor checks the public certificate through
  the proxy and skips the port 80 check. Leave the key out to switch it off;
  `false` is refused.
- **`LEONAID_STAGING_MAILPIT=true`:** Mailpit plays the SMTP relay inside the
  stack. Nothing leaves the server. Set these keys:

  ```sh
  LEONAID_STAGING_MAILPIT=true
  LEONAID_STAGING_MAILPIT_UI_AUTH=operator:<password, at least 16 characters>
  MAIL_SMTP_HOST=mailpit
  MAIL_SMTP_PORT=465
  MAIL_SMTP_MODE=tls
  MAIL_SMTP_CA_FILE=/run/leonaid-staging-mail/ca.pem
  ```

  The stack creates a private CA for Mailpit; only the core worker and Twenty
  trust it. Read the mails, such as sign-in codes, at
  `http://SERVER:8025` with the user and password of
  `LEONAID_STAGING_MAILPIT_UI_AUTH`. Open port 8025 only to your own network.
  The doctor skips the mail provider check. To switch to a real SMTP
  account later, remove the six lines above and set the provider's values.
