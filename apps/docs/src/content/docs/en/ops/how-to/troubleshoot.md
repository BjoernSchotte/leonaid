---
title: Troubleshoot login, mail, and TLS
description: Diagnose common operational failures with Doctor, health checks, and safe correlation data.
docId: DOC-P025
audience: [ops]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Start locally with `./leonaid doctor`, or use `./leonaid pilot-doctor ...
--json` for a pilot. Share the sanitised status, never `.env` contents, tokens,
email addresses, or document bytes.

- **Docker unavailable:** Start Docker or OrbStack and rerun `doctor`.
- **Login code missing:** Check worker, outbox, and mail relay. Mailpit is local
  and starts only with the `dev-mail` profile. Use the latest message; codes are
  single-use and attempts are limited.
- **Too many attempts:** Wait for the displayed cooldown. Do not bypass the
  rate limit or generic authentication response.
- **Local HTTPS:** Use `https://localhost:8443`; port 8080 is diagnostic HTTP.
  Trust the local CA only in a controlled development environment.
- **Public TLS:** Use Pilot Doctor to check DNS, hostname, full trust chain,
  security headers, and at least 14 days of certificate validity. Port 80 stays
  available for ACME and the HTTPS redirect.
- **Writes return 503:** Check `infra/upgrade/maintenance.sh status`. Disable
  maintenance only after dependencies are healthy and contracts pass.

For repeatable faults, record time, release SHA, service, and correlation ID.
Retry write jobs only through their defined safe retry path.
