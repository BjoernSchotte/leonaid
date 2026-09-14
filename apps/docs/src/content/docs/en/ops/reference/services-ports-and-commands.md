---
title: Services, ports, and operator commands
description: Compact reference for the Compose runtime, exposed ports, and operational commands.
docId: DOC-P027
audience: [ops]
diataxis: reference
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

| Service                       | Responsibility                            | Authoritative persistence          |
| ----------------------------- | ----------------------------------------- | ---------------------------------- |
| Caddy                         | sole web entry point and TLS              | Caddy data for public certificates |
| FastAPI Core + worker         | auth, policies, domain operations, outbox | Core PostgreSQL                    |
| Web / PWA / Public / Campaign | admin, acquisition, and public UIs        | no authoritative domain data       |
| Twenty Server/Worker          | companies and people                      | Twenty PostgreSQL and files        |
| RustFS                        | private immutable document bytes          | RustFS volume                      |
| Mail relay                    | login, invitation, and invoice mail       | external provider; local Mailpit   |

Locally only Caddy publishes `127.0.0.1:8443` for HTTPS and
`127.0.0.1:8080` for diagnostic HTTP. The pilot overlay exposes only 80/443.
Databases, Redis, S3, and internal APIs stay inside Compose networks.

Key commands are `bootstrap`, `doctor`, `dev`, `check`, `backup`, `restore`,
`pilot-doctor`, `pilot-deploy`, `pilot-release`, `pilot-backup`,
`pilot-restore`, `test-handoff`, `test-backup`, and `test-upgrade`. Run
`./leonaid help` for the current complete list; the CLI is authoritative when
this reference differs.
