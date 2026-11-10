---
title: Requirements and configuration
description: Reference for local and pilot prerequisites, environment files, and secret boundaries.
docId: DOC-P026
audience: [ops]
diataxis: reference
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 30c252a22ffbcc5a41735023446c40168b5cc260
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

| Area        | Local                                                | Pilot/production                                                  |
| ----------- | ---------------------------------------------------- | ----------------------------------------------------------------- |
| Host        | Git, Docker, Compose v2, at least 5 GiB free         | Linux host, Docker/Compose, public domains, ports 80/443          |
| Environment | ignored `.env.local` created by `bootstrap`          | completed template outside Git, owner-only mode `0600`            |
| Images      | locked development images                            | release images with both tag and digest                           |
| Identity    | `LEONAID_ENV=local` and separate random local values | stage, Compose project, bucket, and full release SHA must agree   |
| Backup      | optional for development                             | external Restic target, separate password and backend credentials |
| Mail/TLS    | optional Mailpit, local Caddy CA                     | dedicated SMTP account and public DNS/TLS evidence                |

Versioned `.env.example` contains generator placeholders only. `./leonaid
bootstrap` replaces them locally and never overwrites an existing `.env.local`.
Production values do not come from that local file.

Secrets belong in neither Git, process arguments, browser configuration, logs,
nor public artifacts. The Twenty integration key is rotated separately and
injected only into Core processes. Check the effective configuration with
`pilot-doctor` before every pilot mutation.

## Web Push: notifications of the acquisition app

The acquisition app sends notifications through the push services of the
browser vendors (Web Push with VAPID, ADR-0017). The installation needs two
values for this; the API and the worker get the same ones.

| Variable                    | Meaning                                                                                                                                                                                              |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LEONAID_VAPID_PRIVATE_KEY` | Private P-256 key of the installation, base64url of the 32-byte scalar. `./leonaid bootstrap` (local) and `./leonaid pilot-secrets` (pilot) create it. The API hands out the public half only.      |
| `LEONAID_VAPID_SUBJECT`     | The operator's contact that the push services read from every push: `mailto:address` or an `https:` address.                                                                                        |

- **Without the key** (both values empty) notifications are "not configured":
  the page **Benachrichtigungen** says so and the worker sends nothing. An
  installation that upgrades to this version therefore starts unchanged.
- **With the key** `LEONAID_VAPID_SUBJECT` must be set. In production the API
  and the worker refuse a contact with a reserved name (`example.org`,
  `.invalid`, `localhost`). The template `infra/pilot/production.env.example`
  carries `mailto:operations@example.org`: replace the address. Otherwise
  `pilot-doctor` reports `web_push_settings_invalid`, and the worker ends at
  start with `worker.configuration.invalid`.
- **The key stays for the life of the installation.** Every registration of a
  device is bound to it. A new key ends all registrations; members then
  switch notifications on again. The key belongs in the backup of the
  environment file.
- **Egress:** the worker sends to `fcm.googleapis.com` and `jmt17.google.com`
  (Chrome, Edge on Android), `updates.push.services.mozilla.com` (Firefox),
  `web.push.apple.com` (Safari, iPhone, iPad) and hosts below
  `notify.windows.com` (Edge on Windows), port 443. In the pilot it reaches
  them through the `mail-egress` network, in the dev stack through
  `geocoder-egress`. Test stacks have no egress. It never sends to other
  hosts; another push service needs a new version.
- **Switching on:** set key and contact, restart the services, activate the
  members' privacy notice with the section "Benachrichtigungen auf deinem
  Gerät", then switch on **Benachrichtigungen in der Akquise-App** under
  **System › Feature-Flags**. Afterwards check on a real Android phone and a
  real iPhone with **Test senden** (see
  [Switch on notifications](../../../user/how-to/switch-on-notifications/)).

What the worker does for this is described under
[Services, ports, and operator commands](../services-ports-and-commands/).
