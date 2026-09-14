---
title: Upgrade and roll back
description: Update pinned Core, Twenty, and RustFS versions behind a maintenance boundary with a tested recovery path.
docId: DOC-P024
audience: [ops]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

First update `infra/locks/external-systems.lock`, `infra/locks/images.env`, and
`infra/upgrade/compatibility-matrix.json`. Read release notes and migrations,
run `./leonaid check` and `./leonaid test-upgrade`, and record the maintenance
window, owner, and a fresh recovery point.

1. Run `infra/upgrade/maintenance.sh enable` and verify that writes return
   `503 maintenance_mode` with `Retry-After`.
2. Create and verify an encrypted backup.
3. Update RustFS and start Twenty once to initialise its prerequisites.
4. Stop Twenty Server and run its official `command:prod
run-instance-commands` and `command:prod upgrade` commands through the
   pinned Compose service. Both must exit with zero.
5. Migrate Core explicitly, start services, and verify images, schemas, health
   checks, the Golden contract, and the browser journey.
6. Disable maintenance only after those checks pass.

After the first schema write, rollback means restore. Never start an older
image against a forward-migrated database. Keep writes blocked, stop the
failed project, and restore the same recovery point into a new, explicitly
confirmed project.
