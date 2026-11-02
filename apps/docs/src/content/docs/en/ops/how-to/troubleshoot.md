---
title: Troubleshoot login, mail, and TLS
description: Diagnose common operational failures with Doctor, health checks, and safe correlation data.
docId: DOC-P025
audience: [ops]
diataxis: how-to
contentRevision: 4
reviewedRevision: 4
verifiedAgainst: 387fe4766a067c6c8ff40079cc4f197824599259
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
- **Twenty CRM check fails:** `doctor` (with the dev stack running) and the
  `pilot-deploy`/`pilot-release` gates of Pilot Doctor ask the running API
  whether Twenty has the `leonaidMatchKey` field and accepts its integration
  key. Locally run `./leonaid provision-twenty`; in a pilot run
  `./leonaid pilot-release --twenty-bootstrap-file FILE`. The check also
  counts records without a key; run `repair-crm-match-keys` to close that gap
  (pilot: `pilot-repair-crm-match-keys --env-file FILE`, which the
  `leonaid-crm-repair` timers run on schedule and which skips while
  maintenance mode is on).
- **No mail from the CRM (pilot):** Twenty's worker sends verification,
  password reset and invitation mail through the `MAIL_SMTP_*` relay over
  the `mail-egress` network. Check the `twenty-worker` logs for the SMTP
  error, that `MAIL_SMTP_PORT` matches `MAIL_SMTP_MODE` (465 only with
  `tls`), and that the relay certificate comes from a public CA.
- **Writes return 503:** Check `infra/upgrade/maintenance.sh status`. Disable
  maintenance only after dependencies are healthy and contracts pass.

For repeatable faults, record time, release SHA, service, and correlation ID.
Retry write jobs only through their defined safe retry path.

## Roll back the documentation website

If the HTTPS smoke fails after a Pages deployment, open the last green
`Documentation` run from `main`, verify its manifest SHA, and rerun that exact
workflow run. GitHub Pages atomically activates the newly produced artifact.
Then verify the German and English entries, search, the language switch, and
`build-manifest.json`. Never use a pull-request run as a rollback source.

The separate `Documentation watchdog` workflow opens a repository issue
immediately when a `main` run fails. It also checks every six hours whether no
successful publication has occurred for more than 30 hours, placing the
intended alert before the 36-hour boundary. A successful recovery run closes
the issue. The maintainer must enable notifications for repository issues.
