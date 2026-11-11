---
title: Operations and recovery model
description: How health checks, maintenance, backup, release, and external acceptance form the operating boundary.
docId: DOC-P029
audience: [ops]
diataxis: explanation
contentRevision: 2
reviewedRevision: 2
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

A green container health check proves reachability, not a successful migration
or domain integrity. LeonAid combines technical readiness with explicit
migration commands, Golden contracts, and browser journeys. Pilot Doctor adds
checks for the external environment and unresolved decisions.

The API is ready when PostgreSQL and object storage respond. Twenty (CRM)
counts only when `TWENTY_INTEGRATION_API_KEY` is set; without the key the CRM
features are off. Production needs the key: without it Pilot Doctor fails
instead of reporting an installation without CRM as ready.

Before a schema-changing release, operators create an encrypted, verified
recovery point. Maintenance mode blocks new writes while dependent systems
migrate in a defined order. After a schema write, the safe recovery path is a
fresh-volume restore, not an older image running against newer data.

An upgrade is one command, like in other self-hosted projects: it checks
that the release can read the installed database, backs up, migrates and
checks health. Staging is optional: restore a production backup on a staging
host and run the same upgrade there first. Configuration, secrets, domains,
buckets, SMTP, and backup targets stay separate between environments. Synthetic tests prove the mechanism;
operators must additionally verify DNS, TLS, mail delivery, restore time, and
business approval in the real environment.
