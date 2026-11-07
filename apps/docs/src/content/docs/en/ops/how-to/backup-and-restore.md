---
title: Back up and restore into a fresh environment
description: Encrypt LeonAid data and perform a controlled restore into fresh volumes.
docId: DOC-P023
audience: [ops]
diataxis: how-to
contentRevision: 5
reviewedRevision: 5
verifiedAgainst: ee007bf6c2e21edf0b939ee5641b3a9f98674560
reviewer: Claude Code (Prüfung durch Björn Schotte offen)
---

Prepare an external Restic target, a password file, and optionally a backend
credentials file. Both files use mode `0600` and stay outside Git and the
backup repository.

1. For a pilot installation, run `./leonaid pilot-backup --env-file ENV
--backup-manifest MANIFEST --password-file PASSWORD --credentials-file
CREDENTIALS`.
2. Inspect the manifest and successful `restic check --read-data`. The recovery
   point contains both PostgreSQL databases, Twenty files, the entire RustFS
   volume and, in a pilot, the Caddy data volume with the certificates and
   the ACME account of every host. A restored proxy therefore starts without
   requesting new certificates, but only with `pilot-restore --with-tls-state`:
   use it when you restore the installation itself onto a new server with the
   same host names. Staging and drill targets get no production keys and
   request their own certificates. The archive holds private keys; treat the
   repository password accordingly. It excludes the Valkey queue store (`twenty-redis`), Mailpit,
   images, and plaintext secrets. A restored project starts with an empty
   queue store; `twenty-server` registers its cron jobs again. With
   `LEONAID_CMS_ENABLED=true` and a completed CMS setup the manifest has
   schema version 2 and also holds the CMS database (`emdash.dump`) and the
   CMS setup state (`cms-bootstrap-state.tar`); the CMS media are in the
   RustFS volume. The doctor then refuses a backup without them. While the
   setup is not complete, the backup leaves the unfinished CMS out.
3. Create an empty `leonaid-restore-<name>` project and a separate target
   environment that references the same external repository.
4. Run `./leonaid pilot-restore` with source and target environments, manifest,
   secret files, and exact confirmation `--confirm RESTORE:leonaid-restore-<name>`.
5. Verify health checks, the Golden contract, document hashes, sessions, and
   the browser journey before releasing the target.

The backup decides the restore topology. With a schema 2 backup the target
needs `LEONAID_CMS_ENABLED=true`; `pilot-restore` restores and verifies the
CMS database with the target's verified `campaign-site` image and leaves the whole target stopped
("application remains stopped pending release verification"). Start it with
`./leonaid pilot-deploy` and `release-manifest-cms.json`; the deploy checks
the CMS state before anything starts.

Restore never overwrites an existing environment. Survey data additionally
requires the independently retained erasure checkpoint and its required
freshness time. The current PoC objectives are an RPO of at most 24 hours, an
RTO of at most two hours, and a full drill at least quarterly and before
schema-changing upgrades.
