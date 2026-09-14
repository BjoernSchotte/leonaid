---
title: Requirements and configuration
description: Reference for local and pilot prerequisites, environment files, and secret boundaries.
docId: DOC-P026
audience: [ops]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
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
