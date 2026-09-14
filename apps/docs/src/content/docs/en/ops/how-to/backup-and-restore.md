---
title: Back up and restore into a fresh environment
description: Encrypt LeonAid data and perform a controlled restore into fresh volumes.
docId: DOC-P023
audience: [ops]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

Prepare an external Restic target, a password file, and optionally a backend
credentials file. Both files use mode `0600` and stay outside Git and the
backup repository.

1. For a pilot installation, run `./leonaid pilot-backup --env-file ENV
--backup-manifest MANIFEST --password-file PASSWORD --credentials-file
CREDENTIALS`.
2. Inspect the manifest and successful `restic check --read-data`. The recovery
   point contains both PostgreSQL databases, Twenty files, and the entire
   RustFS volume. It excludes Redis, Mailpit, images, and plaintext secrets.
3. Create an empty `leonaid-restore-<name>` project and a separate target
   environment that references the same external repository.
4. Run `./leonaid pilot-restore` with source and target environments, manifest,
   secret files, and exact confirmation `--confirm RESTORE:leonaid-restore-<name>`.
5. Verify health checks, the Golden contract, document hashes, sessions, and
   the browser journey before releasing the target.

Restore never overwrites an existing environment. Survey data additionally
requires the independently retained erasure checkpoint and its required
freshness time. The current PoC objectives are an RPO of at most 24 hours, an
RTO of at most two hours, and a full drill at least quarterly and before
schema-changing upgrades.
