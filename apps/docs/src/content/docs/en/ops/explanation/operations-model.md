---
title: Operations and recovery model
description: How health checks, maintenance, backup, release, and external acceptance form the operating boundary.
docId: DOC-P029
audience: [ops]
diataxis: explanation
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

A green container health check proves reachability, not a successful migration
or domain integrity. LeonAid combines technical readiness with explicit
migration commands, Golden contracts, and browser journeys. Pilot Doctor adds
checks for the external environment and unresolved decisions.

Before a schema-changing release, operators create an encrypted, verified
recovery point. Maintenance mode blocks new writes while dependent systems
migrate in a defined order. After a schema write, the safe recovery path is a
fresh-volume restore, not an older image running against newer data.

Production receives only a SHA already verified in staging with the identical
manifest. Configuration, secrets, domains, buckets, SMTP, and backup targets
stay separate between environments. Synthetic tests prove the mechanism;
operators must additionally verify DNS, TLS, mail delivery, restore time, and
business approval in the real environment.
